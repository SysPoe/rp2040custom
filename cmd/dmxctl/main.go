package main

import (
	"bufio"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
)

const (
	ports    = 4
	slots    = 512
	frameLen = slots + 1
)

type universe [frameLen]byte

func main() {
	portName := flag.String("port", "", "serial port, e.g. /dev/ttyACM0 or COM3")
	baud := flag.Int("baud", 115200, "serial baud rate")
	flag.Parse()

	if *portName == "" {
		printPortHint()
		fmt.Fprintln(os.Stderr, "error: pass -port")
		os.Exit(2)
	}

	serial, err := openSerial(*portName, *baud)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open serial: %v\n", err)
		os.Exit(1)
	}
	defer serial.Close()

	var state [ports]universe
	if err := sendAll(serial, &state); err != nil {
		fmt.Fprintf(os.Stderr, "initial send: %v\n", err)
		os.Exit(1)
	}
	printEcho(serial)

	fmt.Printf("connected to %s at %d baud\n", *portName, *baud)
	printHelp()
	repl(serial, &state)
}

func repl(serial io.ReadWriter, state *[ports]universe) {
	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Print("dmx> ")
		if !scanner.Scan() {
			fmt.Println()
			return
		}
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		if err := runCommand(serial, state, line); err != nil {
			fmt.Printf("error: %v\n", err)
		}
	}
}

func runCommand(serial io.ReadWriter, state *[ports]universe, line string) error {
	fields := strings.Fields(line)
	if len(fields) == 0 {
		return nil
	}

	switch strings.ToLower(fields[0]) {
	case "h", "help", "?":
		printHelp()
	case "q", "quit", "exit":
		os.Exit(0)
	case "clear", "blackout":
		for port := range state {
			for slot := 1; slot <= slots; slot++ {
				state[port][slot] = 0
			}
		}
		if err := sendAll(serial, state); err != nil {
			return err
		}
		printEcho(serial)
	case "set":
		port, values, err := parseSet(fields[1:])
		if err != nil {
			return err
		}
		if port < 0 {
			for i := range state {
				applyValues(&state[i], values)
			}
			if err := sendAll(serial, state); err != nil {
				return err
			}
			printEcho(serial)
			return nil
		}
		applyValues(&state[port], values)
		if err := sendPort(serial, port, state[port][:]); err != nil {
			return err
		}
		printEcho(serial)
	case "slot":
		port, slot, value, err := parseSlot(fields[1:])
		if err != nil {
			return err
		}
		state[port][slot] = byte(value)
		if err := sendPort(serial, port, state[port][:]); err != nil {
			return err
		}
		printEcho(serial)
	case "show":
		showState(state)
	default:
		return fmt.Errorf("unknown command %q; try help", fields[0])
	}
	return nil
}

func parseSet(args []string) (int, []byte, error) {
	if len(args) == 0 {
		return -1, nil, errors.New("usage: set [port 1-4] v1,v2,...")
	}

	port := -1
	valueText := strings.Join(args, " ")
	if len(args) >= 2 {
		if parsedPort, err := strconv.Atoi(args[0]); err == nil && parsedPort >= 1 && parsedPort <= ports {
			port = parsedPort - 1
			valueText = strings.Join(args[1:], " ")
		}
	}

	values, err := parseValues(valueText)
	if err != nil {
		return -1, nil, err
	}
	return port, values, nil
}

func parseSlot(args []string) (int, int, int, error) {
	if len(args) != 3 {
		return 0, 0, 0, errors.New("usage: slot <port 1-4> <slot 1-512> <value 0-255>")
	}
	port, err := parseRange(args[0], 1, ports, "port")
	if err != nil {
		return 0, 0, 0, err
	}
	slot, err := parseRange(args[1], 1, slots, "slot")
	if err != nil {
		return 0, 0, 0, err
	}
	value, err := parseRange(args[2], 0, 255, "value")
	if err != nil {
		return 0, 0, 0, err
	}
	return port - 1, slot, value, nil
}

func parseValues(text string) ([]byte, error) {
	parts := strings.FieldsFunc(text, func(r rune) bool {
		return r == ',' || r == ' ' || r == '\t'
	})
	if len(parts) == 0 || len(parts) > slots {
		return nil, fmt.Errorf("expected 1-%d values", slots)
	}

	values := make([]byte, len(parts))
	for i, part := range parts {
		value, err := parseRange(part, 0, 255, "value")
		if err != nil {
			return nil, err
		}
		values[i] = byte(value)
	}
	return values, nil
}

func parseRange(text string, min int, max int, label string) (int, error) {
	value, err := strconv.Atoi(text)
	if err != nil {
		return 0, fmt.Errorf("%s %q is not a number", label, text)
	}
	if value < min || value > max {
		return 0, fmt.Errorf("%s must be %d-%d", label, min, max)
	}
	return value, nil
}

func applyValues(u *universe, values []byte) {
	for i, value := range values {
		u[i+1] = value
	}
}

func sendAll(w io.Writer, state *[ports]universe) error {
	for port := range state {
		if err := sendPort(w, port, state[port][:]); err != nil {
			return err
		}
	}
	return nil
}

func sendPort(w io.Writer, port int, payload []byte) error {
	if port < 0 || port >= ports {
		return fmt.Errorf("port must be 0-%d", ports-1)
	}
	if len(payload) != frameLen {
		return fmt.Errorf("payload must be %d bytes", frameLen)
	}

	frame := make([]byte, 5+len(payload))
	frame[0] = 0x44
	frame[1] = 0x4d
	frame[2] = byte(port)
	binary.LittleEndian.PutUint16(frame[3:5], uint16(len(payload)))
	copy(frame[5:], payload)

	return writeFull(w, frame)
}

func writeFull(w io.Writer, data []byte) error {
	for len(data) > 0 {
		n, err := w.Write(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		data = data[n:]
	}
	return nil
}

func printEcho(r io.Reader) {
	buf := make([]byte, 1024)
	n, err := r.Read(buf)
	if err != nil || n == 0 {
		return
	}
	text := strings.TrimRight(string(buf[:n]), "\r\n")
	if text != "" {
		fmt.Println(text)
	}
}

func printHelp() {
	fmt.Println(`commands:
  set 255,255,255        set slots 1-3 on all DMX ports
  set 2 255,0,0          set slots 1-3 on DMX port 2 only
  slot 1 10 255          set DMX port 1, slot 10 to 255
  clear                  set all slots on all ports to 0
  show                   print the first 16 slots for each port
  help                   show this help
  quit                   exit`)
}

func showState(state *[ports]universe) {
	for port, universe := range state {
		fmt.Printf("port %d:", port+1)
		for slot := 1; slot <= 16; slot++ {
			fmt.Printf(" %d", universe[slot])
		}
		fmt.Println()
	}
}
