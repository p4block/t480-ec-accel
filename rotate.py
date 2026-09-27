#!/usr/bin/env python3
"""Calibrated Sway rotation from the T480 EC input device."""
import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import select
import statistics
import subprocess
import time

from evdev import InputDevice, ecodes, list_devices

NAME = 'ThinkPad T480 EC accelerometer'
STATE = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 't480-auto-rotate.json'


def device():
    for path in list_devices():
        dev = InputDevice(path)
        if dev.name == NAME:
            return dev
        dev.close()
    raise RuntimeError('T480 accelerometer input device not found')


def frames(dev, timeout=3):
    """Only yield complete frames with a fresh driver heartbeat."""
    axes = {ecodes.ABS_X: dev.absinfo(ecodes.ABS_X).value,
            ecodes.ABS_Y: dev.absinfo(ecodes.ABS_Y).value}
    heartbeat = False
    dropped = False
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([dev.fd], [], [], remaining)[0]:
            raise RuntimeError('Accelerometer data stale; stopping rotation')
        for event in dev.read():
            if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                dropped = True
                heartbeat = False
            elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                if dropped:
                    for axis in axes:
                        axes[axis] = dev.absinfo(axis).value
                    dropped = False
                    heartbeat = False
                elif heartbeat:
                    deadline = time.monotonic() + timeout
                    heartbeat = False
                    yield axes[ecodes.ABS_X], axes[ecodes.ABS_Y]
            elif not dropped and event.type == ecodes.EV_ABS and event.code in axes:
                axes[event.code] = event.value
            elif not dropped and event.type == ecodes.EV_MSC and event.code == ecodes.MSC_TIMESTAMP:
                heartbeat = True


def sway(*args):
    result = subprocess.run(['swaymsg', '-r', *args], check=True,
                            capture_output=True, text=True, timeout=5)
    return json.loads(result.stdout)


def output_name(requested):
    outputs = [o['name'] for o in sway('-t', 'get_outputs') if o['active']]
    if requested:
        if requested not in outputs:
            raise RuntimeError(f'Output {requested} is not active')
        return requested
    internal = [o for o in outputs if o.startswith('eDP-')]
    if len(internal) != 1:
        raise RuntimeError('Specify --output; no unique active eDP output')
    return internal[0]


def transform(output, angle):
    # Quote the name for Sway's command parser, not for a shell.
    result = sway('output', json.dumps(output), 'transform', str(angle))
    if not result or not all(item.get('success') for item in result):
        raise RuntimeError(f'Sway rejected transform: {result}')


def load_calibration(path):
    data = json.loads(path.read_text())
    poses = data['poses']
    if set(poses) != {'0', '90', '180', '270'}:
        raise ValueError('Calibration requires all four orientations')
    for xy in poses.values():
        if len(xy) != 2 or not all(math.isfinite(v) and 0 <= v <= 65535 for v in xy):
            raise ValueError('Invalid calibration values')
    separation = min(math.dist(a, b) for i, a in enumerate(poses.values())
                     for b in list(poses.values())[i + 1:])
    if separation < 20:
        raise ValueError('Calibration poses are not distinct enough')
    return poses, separation * 0.35


def classify(xy, poses, radius):
    angle, center = min(poses.items(), key=lambda item: math.dist(xy, item[1]))
    return angle if math.dist(xy, center) <= radius else None


def calibrate(args):
    output = output_name(args.output)
    poses = {}
    print('Keep the laptop base near vertical for calibration. The sensor is in the base, not the lid.')
    print('For each transform, hold the laptop so the displayed desktop is upright, then press Enter.')
    current = next(o['transform'] for o in sway('-t', 'get_outputs') if o['name'] == output)
    try:
        for angle in ('0', '90', '180', '270'):
            transform(output, angle)
            input(f'Transform {angle}: position laptop, hold still, press Enter: ')
            with closing(device()) as dev:
                stream = frames(dev)
                next(stream)  # Discard the first received frame.
                values = [next(stream) for _ in range(6)]
            poses[angle] = [statistics.median(row[i] for row in values) for i in (0, 1)]
            if max(math.dist(row, poses[angle]) for row in values) > 15:
                raise RuntimeError('Laptop moved during calibration; retry while holding still')
            print(f'  X/Y: {poses[angle]}')
    finally:
        transform(output, current)
    candidate = args.calibration.with_suffix('.tmp')
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(json.dumps({'poses': poses}, indent=2) + '\n')
    try:
        load_calibration(candidate)
        candidate.replace(args.calibration)
    finally:
        candidate.unlink(missing_ok=True)
    print(f'Saved {args.calibration}. Start with: systemctl --user start t480-auto-rotate')


def run(args):
    poses, radius = load_calibration(args.calibration)
    output = output_name(args.output)
    last = None
    pending = None
    since = 0
    with closing(device()) as dev:
        for xy in frames(dev):
            angle = classify(xy, poses, radius)
            now = time.monotonic()
            if angle != pending:
                pending, since = angle, now
            if angle is not None and angle != last and now - since >= 1.5:
                transform(output, angle)
                last = angle
                print(f'transform={angle} x={xy[0]} y={xy[1]}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['sample', 'calibrate', 'run'])
    parser.add_argument('--output')
    parser.add_argument('--calibration', type=Path, default=STATE)
    args = parser.parse_args()
    if args.mode == 'calibrate':
        calibrate(args)
    elif args.mode == 'run':
        run(args)
    else:
        with closing(device()) as dev:
            for x, y in frames(dev):
                print(f'x={x} y={y}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
