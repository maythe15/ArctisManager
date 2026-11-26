# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## Added
- Configurable ChatMix groups: choose which output channels (Game, Chat, Media, Aux) follow the media or chat side of ChatMix from the Mixer page's Media Mix Group and Chat Mix Group cards. Saved as `mix_groups` in `general_settings.yaml` and exposed over D-Bus via `SetMixGroup` and the `mix_groups` settings field.
- Arctis Nova Pro Wireless: equalizer controls (preset picker plus 10 custom bands, -10 to +10 dB in 0.5 dB steps). The saved preset and bands are re-applied when the headset is initialized, and preset changes are followed by the station's save command (`0x06 0x09`), matching HeadsetControl.
- Arctis Nova Pro Wireless: EQ preset and custom bands changed on the base station now show up in the app (station reports `07 2e <preset>` and `07 31 <band> <value>`).
- GUI: new Equalizer page. EQ presets moved off the Device page. Presets are chips; band gains are shown as a graphic equalizer with a dB grid, a response curve through the bands, and a draggable handle per band (scroll wheel, arrow keys and double-click-to-reset work too). Each drag sends one change, on release. "Reset to flat", to the right of the Band Gains title, sets every band back to 0 dB. While a fixed (non-Custom) preset is selected, the graph shows that preset's curve and is read-only; select Custom to edit the bands. The page lists the settings of any `equalizer*` YAML section, so other devices get it from their YAML alone.
- GUI: Settings page controls restyled to match the rest of the app. The audio redirect settings are now in a General card, on/off switches are dark toggles that fill with the accent colour when on, and the output device picker matches the other dropdowns. Option buttons for `discrete_map` settings (e.g. Gain on the Device page) are now chips like the Equalizer presets.
- GUI: buttons, combo boxes, sliders, checkboxes and tabs show a pointing-hand cursor when enabled.
- D-Bus: each device setting in `settings_config` carries its YAML `section`.
- Device YAML: `update_sequence` can be a list of commands, sent in order, and can use `settings.<name>` tokens to include other settings' current values in one command.
- Device YAML: optional `band_label` for equalizer band sliders (e.g. `32 Hz`), shown under the band on the Equalizer page.
- Device YAML: optional `preset_bands` on an equalizer preset, giving the band values of each fixed preset for the Equalizer page, and `preset_bands_approximate: true` to mark them as approximations. The Nova Pro Wireless sets it: Bass Boost and Smiley use the SteelSeries factory curves as HeadsetControl defines them for the Arctis Nova 7 (not yet confirmed on the Nova Pro), and Focus was read off the station's own EQ display.
- Device YAML: optional `settings_feedback` section mapping device packets to settings changed on the device itself.
- Device YAML: optional `device_shutdown` sequence, sent when the daemon stops.
- Daemon: `LAM_LOG_LEVEL=DEBUG` logs raw device packets.

## Changed
- Virtual output sinks (Game/Chat/Media/Aux) are now a single PipeWire node each: a null sink (with `monitor.channel-volumes=true`, so ChatMix still applies) whose monitor ports are linked straight to the headset with `pw-link`. This replaces the null sink plus `module-loopback`, going from 12 nodes to 4 for the four outputs, and graph tools such as qpwgraph now show an unbroken path from each app to the headset. When `pw-link` is not installed, or linking fails, the daemon falls back to `module-remap-sink` (two nodes per output, no visible link between them). Older setups are rebuilt automatically, and existing links are re-checked each time the daemon sets up the headset.

## Fixed
- Arctis Nova Pro Wireless: the base station's own EQ menu is no longer locked while the daemon runs. The init sequence now sends only identified commands plus ChatMix enable (`0x06 0x49 0x01`); one of the unidentified commands it used to send locked the menu until the station was power-cycled. Verified on hardware: station EQ menu, app EQ (presets and custom bands), ChatMix, battery and mic LED all work.
- Arctis Nova Pro Wireless: the ChatMix status group is shown.
- Daemon froze (GUI showed no device after a restart) when dragging the EQ sliders. dbus-next 0.2.3 treats a full socket send buffer (`BlockingIOError`, EAGAIN) as fatal and tears the bus down; a burst of SettingsChanged broadcasts, one per slider tick, could fill it. The daemon and GUI now patch dbus-next's writer to wait until the socket is writable (`dbus_compat.py`), and the daemon combines bursts of setting changes into one SettingsChanged signal.
- GUI: dragging sliders no longer ends in "too many open files", and D-Bus calls made from different threads (e.g. "Assign selected stream" on the Routing page, saving/loading profiles) no longer fail silently. dbus-next never closes bus sockets and a bus only works on the event loop that created it; all requests now share one connection on one background event loop (reconnecting if it drops), which also keeps rapid setting changes in order. Failures are logged.
- GUI: the Routing page status line reports whether moving a stream succeeded, and the selected stream and output are no longer reset whenever settings refresh.
- Opening the GUI no longer fails with `arctis-manager.service: Start request repeated too quickly`. The GUI and `lam-cli setup` reset a unit that hit its start limit before starting it, and report a failed start instead of crashing.
- The daemon waits up to 30 seconds for the PulseAudio/PipeWire server at login instead of exiting at once. The unit now starts after `pipewire-pulse.service`.
- A stale `lam-daemon.pid` whose PID was reused by another process no longer stops the daemon from starting. A daemon that finds another instance running exits with status 3, which systemd does not restart.

## [2.4.1]

## Added
- Support for Arctis Nova Pro Wireless (225d)
- Added install script by @HelpfulSoft1207

## [2.4.0]

## Added
- Support for Nova Pro Wired - @HelpfulSoft1207
- Support for Nova 7 Plus - @debbiedi
- Support for Nova 5X (variant 2264)

## Fixed

- After USB error teardown, the daemon now actively re-detects the device instead of relying solely on systemd to restart it (fixes [#23](https://github.com/elegos/Linux-Arctis-Manager/issues/23))
- `CoreEngine.device_settings` is no longer uninitialized when no recognized device is connected; `lam-gui` no longer crashes with `AttributeError` in that scenario (fixes [#27](https://github.com/elegos/Linux-Arctis-Manager/issues/27))
- Systray app's name set to "Arctis Manager", instead of the anonymous "lam-gui"

## [2.3.1]

## Added

- Single-instance enforcement for `lam-daemon` via PID file in `XDG_RUNTIME_DIR`
- `--replace` flag for `lam-daemon` to stop running instance and start a new one

## Fixed

- USB I/O errors (errno 5/32) after system suspend/resume no longer cause infinite log spam and 100% CPU usage; the daemon now tears down the stale USB handle and waits for the device to re-enumerate, exiting cleanly for systemd to restart if recovery fails (fixes [#23](https://github.com/elegos/Linux-Arctis-Manager/issues/23))

## [2.3.0]

## Added

- `discrete_map` setting type
- `lam-cli setup` all-in-one setup script

## Changed

- Updated `uv` and relative build tools to version 0.10.11
- Updated `slider` configurations to `descrete_map` ones where a mapping was set

## [2.2.1]

# Fixed

- Proper udev file content generation

## [2.2.0]

## Added

- Support for devices communicating on control endpoint (0x00)
- Support for Arctis Nova 7 family (thanks villain @ Discord!)
- Support for Arctis Nova 5 family (thanks @nrwlia!)
- `StatusChanged` and `SettingsChanged` Dbus signals (subscription model instead of polling one)

## Changed

- GUI now subscribes to Dbus signals instead of continuously poll the Dbus interfaces

## Fixed

- Re-initialize device on system wake up (after sleep)
- Ensure applications directory exists before creating the desktop entry
- Proper USB device claim
- Fix an issue incorrectly initializing the TOGGLE UI widget

## [2.1.0] - 4 March 2026

### Fixed

- Initialize device on awake after sleep
