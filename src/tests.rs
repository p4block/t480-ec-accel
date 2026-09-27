// SPDX-License-Identifier: WTFPL
use super::*;

#[test]
fn measured_poses_and_ambiguous_tilts() {
    let p = LegacyProfile::default();
    for (xy, expected) in [
        ([703, 563], "270"),
        ([369, 564], "90"),
        ([573, 696], "normal"),
        ([570, 360], "180"),
        ([572, 571], "normal"),
        ([580, 582], "normal"),
    ] {
        assert_eq!(p.classify(xy), Some(expected));
    }
    assert_eq!(p.classify([680, 680]), None);
    assert_eq!(p.classify([630, 571]), None);
}

#[test]
fn short_tilts_and_ambiguity_reset_dwell() {
    let start = Instant::now();
    let mut d = Debounce::new(start);
    for (ms, target, expected) in [
        (0, Some("90"), None),
        (900, Some("90"), None),
        (950, None, None),
        (1000, Some("90"), None),
        (1900, Some("90"), None),
        (2100, Some("90"), Some("90")),
        (2200, Some("normal"), None),
        (3300, Some("normal"), Some("normal")),
    ] {
        assert_eq!(
            d.update(target, start + Duration::from_millis(ms)),
            expected
        );
    }
}

#[test]
fn profile_validation() {
    let valid = br#"{"center":[572,571],"positive":[131,125],"negative":[203,211]}"#;
    assert_eq!(
        Profile::parse(valid).unwrap().classify([703, 563]),
        Some("270")
    );
    for invalid in [
        r#"{}"#,
        r#"{"center":[0,0],"positive":[0,1],"negative":[1,1]}"#,
        r#"{"center":[true,0],"positive":[1,1],"negative":[1,1]}"#,
        r#"{"center":[0,0,0],"positive":[1,1],"negative":[1,1]}"#,
        r#"{"center":[0,0],"positive":[1,1],"negative":[-1,1]}"#,
    ] {
        assert!(Profile::parse(invalid.as_bytes()).is_err());
    }
}

#[test]
fn selects_only_one_active_internal_display() {
    let outputs = serde_json::json!([
        {"name":"LVDS-1","active":true,"transform":"flipped-90"},
        {"name":"HDMI-A-1","active":true,"transform":"normal"},
        {"name":"eDP-1","active":false,"transform":"normal"}]);
    assert_eq!(
        select_output(&outputs, None).unwrap(),
        ("LVDS-1".into(), "flipped-90".into())
    );
    assert_eq!(
        select_output(&outputs, Some("HDMI-A-1")).unwrap().0,
        "HDMI-A-1"
    );
    assert!(select_output(&outputs, Some("eDP-1")).is_err());
    assert!(select_output(&serde_json::json!([]), None).is_err());
}

#[test]
fn fragmented_ipc_and_malformed_headers() {
    for mode in 0..4 {
        let (mut client, mut server) = UnixStream::pair().unwrap();
        let handle = std::thread::spawn(move || {
            let mut request = [0; 14];
            server.read_exact(&mut request).unwrap();
            assert_eq!(&request[..6], b"i3-ipc");
            assert_eq!(u32::from_le_bytes(request[10..14].try_into().unwrap()), 3);
            let body = b"[]";
            let mut reply = b"i3-ipc".to_vec();
            reply.extend_from_slice(
                &(if mode == 2 { 5 * 1024 * 1024u32 } else { 2u32 }).to_le_bytes(),
            );
            reply.extend_from_slice(&(if mode == 1 { 0u32 } else { 3u32 }).to_le_bytes());
            if mode == 3 {
                reply[0] = b'x';
            }
            reply.extend_from_slice(body);
            // read_exact must tolerate fragmented responses.
            for part in reply.chunks(2) {
                if server.write_all(part).is_err() {
                    break;
                }
            }
        });
        let result = ipc_request(&mut client, 3, "");
        if mode == 0 {
            assert_eq!(result.unwrap(), serde_json::json!([]));
        } else {
            assert!(result.is_err());
        }
        handle.join().unwrap();
    }
}

#[test]
fn poll_handles_data_timeout_hangup_and_stop_signal() {
    let signals = Signals::new().unwrap();
    let (reader, mut writer) = UnixStream::pair().unwrap();
    assert_eq!(
        wait(reader.as_raw_fd(), signals.fd.as_raw_fd(), Instant::now()).unwrap(),
        Wake::Timeout
    );
    writer.write_all(b"x").unwrap();
    assert_eq!(
        wait(
            reader.as_raw_fd(),
            signals.fd.as_raw_fd(),
            Instant::now() + STALE
        )
        .unwrap(),
        Wake::Data
    );
    // raise targets this test thread, where Signals blocked SIGTERM.
    unsafe {
        libc::raise(libc::SIGTERM);
    }
    let start = Instant::now();
    assert_eq!(
        wait(reader.as_raw_fd(), signals.fd.as_raw_fd(), start + STALE).unwrap(),
        Wake::Stop
    );
    assert!(start.elapsed() < Duration::from_secs(1));
    drop(writer);
    assert!(wait(
        reader.as_raw_fd(),
        signals.fd.as_raw_fd(),
        Instant::now() + STALE
    )
    .is_err());
}

#[test]
fn dry_run_preserves_original_and_never_uses_ipc() {
    let sway = Sway {
        path: "/nonexistent/thinkpad-test.sock".into(),
    };
    let mut r = Rotation {
        sway: &sway,
        output: "LVDS-1".into(),
        original: "flipped-90".into(),
        current: "flipped-90".into(),
        dry_run: true,
    };
    r.set("180").unwrap();
    assert_eq!(r.current, "180");
    r.restore().unwrap();
    assert_eq!(r.current, "flipped-90");
}

#[test]
fn axes_keep_unchanged_values_and_discard_overflow_events() {
    let mut a = Axes {
        values: [572, 571],
        dropped: false,
    };
    a.event(EV_ABS, 0, 703);
    a.event(EV_SYN, SYN_REPORT, 0);
    assert_eq!(a.values, [703, 571]); // Y was suppressed by input core.
    a.event(EV_SYN, SYN_REPORT, 0); // heartbeat-only report
    assert_eq!(a.values, [703, 571]);
    a.event(EV_ABS, 1, 696);
    assert_eq!(a.values, [703, 696]);
    a.event(EV_SYN, SYN_DROPPED, 0);
    a.event(EV_ABS, 0, 1);
    a.event(EV_ABS, 1, 2);
    assert!(a.dropped);
    assert_eq!(a.values, [703, 696]);
    // Caller snapshots both axes at the next SYN_REPORT before resuming.
    a.values = [369, 564];
    a.dropped = false;
    a.event(EV_ABS, 1, 565);
    assert_eq!(a.values, [369, 565]);
}

#[test]
fn calibrated_poses_and_invalid_profiles() {
    let p = Profile::parse(
        br#"{"poses":{"0":[512,720],"90":[310,512],"180":[512,310],"270":[720,512]}}"#,
    )
    .unwrap();
    assert_eq!(p.classify([310, 512]), Some("90"));
    assert_eq!(p.classify([512, 512]), None);
    assert!(Profile::parse(br#"{"poses":{"0":[0,0]}}"#).is_err());
    assert!(
        Profile::parse(br#"{"poses":{"0":[0,0],"90":[0,0],"180":[0,0],"270":[0,0]}}"#).is_err()
    );
}

#[test]
fn sensor_requires_fresh_heartbeat() {
    use std::os::fd::IntoRawFd;
    let signals = Signals::new().unwrap();
    let (reader, mut writer) = UnixStream::pair().unwrap();
    for (kind, code, value) in [
        (EV_ABS, 0, 99),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, 0, 123),
        (EV_MSC, MSC_TIMESTAMP, 1),
        (EV_SYN, SYN_REPORT, 0),
    ] {
        // SAFETY: input_event is an integer-only C struct; initialize all bytes.
        let mut event: libc::input_event = unsafe { zeroed() };
        event.type_ = kind;
        event.code = code;
        event.value = value;
        let bytes = unsafe {
            std::slice::from_raw_parts(
                (&event as *const libc::input_event).cast::<u8>(),
                size_of::<libc::input_event>(),
            )
        };
        writer.write_all(bytes).unwrap();
    }
    // SAFETY: transfer ownership of the live socket fd into File exactly once.
    let file = unsafe { File::from_raw_fd(reader.into_raw_fd()) };
    let mut sensor = Sensor {
        file,
        cached: Axes {
            values: [0, 456],
            dropped: false,
        },
        recovered: false,
    };
    assert_eq!(sensor.frame(&signals).unwrap(), Some([123, 456]));
}

#[test]
fn profile_save_refuses_existing_temp_symlink() {
    use std::os::unix::fs::symlink;
    let dir = env::temp_dir().join(format!("thinkpad-rotate-test-{}", std::process::id()));
    fs::create_dir(&dir).unwrap();
    let path = dir.join("profile.json");
    let victim = dir.join("untouched");
    fs::write(&victim, b"keep").unwrap();
    let tmp = dir.join(format!(".thinkpad-rotate-{}.tmp", std::process::id()));
    symlink(&victim, &tmp).unwrap();
    assert!(save_profile(&path, b"{}").is_err());
    assert_eq!(fs::read(&victim).unwrap(), b"keep");
    fs::remove_file(&tmp).unwrap();
    save_profile(&path, b"{}").unwrap();
    assert_eq!(fs::read(&path).unwrap(), b"{}");
    fs::remove_dir_all(dir).unwrap();
}
