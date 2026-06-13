//go:build linux

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"syscall"
	"unsafe"
)

func openSerial(name string, baud int) (*os.File, error) {
	if baud != 115200 {
		return nil, fmt.Errorf("only 115200 baud is supported without external Go serial packages")
	}

	fd, err := syscall.Open(name, syscall.O_RDWR|syscall.O_NOCTTY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	if err := syscall.SetNonblock(fd, false); err != nil {
		syscall.Close(fd)
		return nil, err
	}

	var termios syscall.Termios
	if err := ioctl(fd, syscall.TCGETS, uintptr(unsafe.Pointer(&termios))); err != nil {
		syscall.Close(fd)
		return nil, err
	}

	const cbaud = 0x100f
	termios.Iflag = syscall.IGNPAR
	termios.Oflag = 0
	termios.Lflag = 0
	termios.Cflag &^= syscall.CSIZE | syscall.PARENB | syscall.CSTOPB | cbaud
	termios.Cflag |= syscall.CS8 | syscall.CREAD | syscall.CLOCAL | syscall.B115200
	termios.Cc[syscall.VMIN] = 0
	termios.Cc[syscall.VTIME] = 1
	termios.Ispeed = syscall.B115200
	termios.Ospeed = syscall.B115200

	if err := ioctl(fd, syscall.TCSETS, uintptr(unsafe.Pointer(&termios))); err != nil {
		syscall.Close(fd)
		return nil, err
	}

	return os.NewFile(uintptr(fd), name), nil
}

func ioctl(fd int, req uint, arg uintptr) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), uintptr(req), arg)
	if errno != 0 {
		return errno
	}
	return nil
}

func printPortHint() {
	ports := candidatePorts()
	if len(ports) == 0 {
		fmt.Println("no obvious serial ports found; try -port /dev/ttyACM0")
		return
	}
	fmt.Println("candidate serial ports:")
	for _, port := range ports {
		fmt.Printf("  %s\n", port)
	}
}

func candidatePorts() []string {
	patterns := []string{
		"/dev/serial/by-id/*",
		"/dev/ttyACM*",
		"/dev/ttyUSB*",
	}
	var out []string
	seen := map[string]bool{}
	for _, pattern := range patterns {
		matches, _ := filepath.Glob(pattern)
		for _, match := range matches {
			if resolved, err := filepath.EvalSymlinks(match); err == nil {
				match = resolved
			}
			if !seen[match] {
				seen[match] = true
				out = append(out, match)
			}
		}
	}
	sort.Strings(out)
	return out
}
