import importlib.util
from pathlib import Path
import tempfile
import json
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rotate', Path(__file__).with_name('rotate.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class RotationTests(unittest.TestCase):
    def test_pose_classification_rejects_flat_and_intermediate(self):
        poses = {'0': [512, 312], '90': [312, 512], '180': [512, 712], '270': [712, 512]}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'calibration.json'
            p.write_text(json.dumps({'poses': poses}))
            poses, radius = r.load_calibration(p)
        self.assertEqual(r.classify((518, 315), poses, radius), '0')
        self.assertEqual(r.classify((709, 521), poses, radius), '270')
        self.assertIsNone(r.classify((512, 512), poses, radius))
        self.assertIsNone(r.classify((650, 650), poses, radius))

    def test_rejects_indistinguishable_poses(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'calibration.json'
            p.write_text(json.dumps({'poses': {a: [512, 512] for a in ('0','90','180','270')}}))
            with self.assertRaises(ValueError):
                r.load_calibration(p)

    def test_stationary_heartbeat_and_stale_timeout(self):
        from types import SimpleNamespace as N
        c = r.ecodes
        class Device:
            fd = 5
            def absinfo(self, axis): return N(value=512)
            def read(self): return [N(type=c.EV_MSC, code=c.MSC_TIMESTAMP, value=1),
                                    N(type=c.EV_SYN, code=c.SYN_REPORT, value=0)]
        with patch.object(r.select, 'select', side_effect=[([5],[],[]),([],[],[])]):
            stream = r.frames(Device())
            self.assertEqual(next(stream), (512,512))
            with self.assertRaisesRegex(RuntimeError,'stale'):
                next(stream)

    def test_dropped_frame_requires_new_heartbeat(self):
        from types import SimpleNamespace as N
        c = r.ecodes
        class Device:
            fd = 5
            def absinfo(self, axis): return N(value=500+axis)
            def read(self): return [N(type=c.EV_SYN, code=c.SYN_DROPPED, value=0),
                N(type=c.EV_ABS, code=c.ABS_X, value=65535),
                N(type=c.EV_SYN, code=c.SYN_REPORT, value=0),
                N(type=c.EV_MSC, code=c.MSC_TIMESTAMP, value=2),
                N(type=c.EV_SYN, code=c.SYN_REPORT, value=0)]
        with patch.object(r.select, 'select', return_value=([5],[],[])):
            self.assertEqual(next(r.frames(Device())), (500,501))

if __name__ == '__main__': unittest.main()
