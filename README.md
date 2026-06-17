# RP2040 USB CDC to 2-port DMX

Firmware for an RP2040/Pico-class board that receives DMX universe data over
USB CDC serial and transmits it through two MAX485 chips.

## Pinout

| Port  | Connector | MAX485 TX | MAX485 EN |
| ----- | --------- | --------- | --------- |
| DMX 1 | 5-pin XLR | GP0       | GP2       |
| DMX 2 | 5-pin XLR | GP4       | GP6       |

EN pins are driven high for transmit enable.

## USB CDC frame format

Send one binary frame per universe update:

```text
0x44 0x4d  port  len_lo len_hi  payload...
```

- `port`: `0` for DMX 1, `1` for DMX 2.
- `len`: little-endian payload length from `1` to `513`.
- `payload[0]`: DMX start code, normally `0x00`.
- `payload[1..512]`: DMX slots.

Each port continuously retransmits its last received payload at DMX speed using
one RP2040 hardware UART per output. At boot, both ports transmit 513 zero
bytes.

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
rp2040-cdc-2port-dmx.uf2
```

## Client app

An example Go client is in `cmd/dmxctl`. It uses only the Go standard library
and has separate serial backends for Linux and Windows.

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

Build the client yourself:

```sh
GOCACHE="$PWD/.gocache" go build -buildvcs=false -o dmxctl-linux-amd64 ./cmd/dmxctl
GOCACHE="$PWD/.gocache" GOOS=windows GOARCH=amd64 go build -buildvcs=false -o dmxctl-windows-amd64.exe ./cmd/dmxctl
```
