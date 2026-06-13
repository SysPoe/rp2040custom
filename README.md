# RP2040 USB CDC to 4-port DMX

Firmware for an RP2040/Pico-class board that receives DMX universe data over
USB CDC serial and transmits it through four MAX3485 RS-485 drivers.

## Pinout

| Port | Connector | RP2040 TX | RP2040 EN |
| --- | --- | --- | --- |
| DMX 1 | 5-pin XLR | GP0 | GP2 |
| DMX 2 | 5-pin XLR | GP4 | GP6 |
| DMX 3 | 5-pin XLR | GP8 | GP10 |
| DMX 4 | 3-pin XLR | GP12 | GP14 |

EN pins are driven high for transmit enable.

## USB CDC frame format

Send one binary frame per universe update:

```text
0x44 0x4d  port  len_lo len_hi  payload...
```

- `port`: `0` for DMX 1, `1` for DMX 2, `2` for DMX 3, `3` for DMX 4.
- `len`: little-endian payload length from `1` to `513`.
- `payload[0]`: DMX start code, normally `0x00`.
- `payload[1..512]`: DMX slots.

Each port continuously retransmits its last received payload at DMX speed. At
boot, all ports transmit 513 zero bytes.

After each valid frame, the firmware writes an ASCII acknowledgment over USB
CDC:

```text
OK port=1 len=513
```

## Build

```sh
~/.platformio/penv/bin/pio run
```

The UF2 is expected at:

```text
.pio/build/pico/firmware.uf2
```

This repo also includes a ready-to-flash copy:

```text
rp2040-cdc-4port-dmx.uf2
```

## Client app

The Go client is in `cmd/dmxctl`. It uses only the Go standard library and has
separate serial backends for Linux and Windows.

Prebuilt local binaries:

```text
dmxctl-linux-amd64
dmxctl-windows-amd64.exe
```

Run on Linux:

```sh
./dmxctl-linux-amd64 -port /dev/ttyACM0
```

Run on Windows PowerShell:

```powershell
.\dmxctl-windows-amd64.exe -port COM3
```

If you run without `-port` on Linux, the client prints likely `/dev/ttyACM*`,
`/dev/ttyUSB*`, and `/dev/serial/by-id/*` ports.

Interactive commands:

```text
set 255,255,255        set slots 1-3 on all DMX ports
set 2 255,0,0          set slots 1-3 on DMX port 2 only
slot 1 10 255          set DMX port 1, slot 10 to 255
clear                  set all slots on all ports to 0
show                   print the first 16 slots for each port
help                   show help
quit                   exit
```

The client prints the firmware `OK port=N len=513` echo after DMX updates.

Build the client yourself:

```sh
GOCACHE="$PWD/.gocache" go build -buildvcs=false -o dmxctl-linux-amd64 ./cmd/dmxctl
GOCACHE="$PWD/.gocache" GOOS=windows GOARCH=amd64 go build -buildvcs=false -o dmxctl-windows-amd64.exe ./cmd/dmxctl
```
