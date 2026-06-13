//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"syscall"
	"unsafe"
)

const (
	genericRead  = 0x80000000
	genericWrite = 0x40000000
	openExisting = 3
	noparity     = 0
	onestopbit   = 0
	dtrEnable    = 0x00000010
	rtsEnable    = 0x00001000
	purgeTxClear = 0x0004
	purgeRxClear = 0x0008
)

type dcb struct {
	DCBlength  uint32
	BaudRate   uint32
	Flags      uint32
	WReserved  uint16
	XonLim     uint16
	XoffLim    uint16
	ByteSize   byte
	Parity     byte
	StopBits   byte
	XonChar    byte
	XoffChar   byte
	ErrorChar  byte
	EofChar    byte
	EvtChar    byte
	WReserved1 uint16
}

type commTimeouts struct {
	ReadIntervalTimeout         uint32
	ReadTotalTimeoutMultiplier  uint32
	ReadTotalTimeoutConstant    uint32
	WriteTotalTimeoutMultiplier uint32
	WriteTotalTimeoutConstant   uint32
}

var (
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	procGetCommState    = kernel32.NewProc("GetCommState")
	procSetCommState    = kernel32.NewProc("SetCommState")
	procSetCommTimeouts = kernel32.NewProc("SetCommTimeouts")
	procSetupComm       = kernel32.NewProc("SetupComm")
	procPurgeComm       = kernel32.NewProc("PurgeComm")
)

func openSerial(name string, baud int) (*os.File, error) {
	path := windowsPortPath(name)
	ptr, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}

	handle, err := syscall.CreateFile(ptr, genericRead|genericWrite, 0, nil, openExisting, 0, 0)
	if err != nil {
		return nil, err
	}

	if err := setupWindowsSerial(handle, baud); err != nil {
		syscall.CloseHandle(handle)
		return nil, err
	}

	return os.NewFile(uintptr(handle), path), nil
}

func setupWindowsSerial(handle syscall.Handle, baud int) error {
	callBool(procSetupComm, uintptr(handle), 4096, 4096)
	callBool(procPurgeComm, uintptr(handle), purgeTxClear|purgeRxClear)

	cfg := dcb{DCBlength: uint32(unsafe.Sizeof(dcb{}))}
	if err := callBool(procGetCommState, uintptr(handle), uintptr(unsafe.Pointer(&cfg))); err != nil {
		return err
	}

	cfg.BaudRate = uint32(baud)
	cfg.ByteSize = 8
	cfg.Parity = noparity
	cfg.StopBits = onestopbit
	cfg.Flags = 0x00000001 | dtrEnable | rtsEnable

	if err := callBool(procSetCommState, uintptr(handle), uintptr(unsafe.Pointer(&cfg))); err != nil {
		return err
	}

	timeouts := commTimeouts{
		ReadIntervalTimeout:         50,
		ReadTotalTimeoutConstant:    50,
		WriteTotalTimeoutMultiplier: 10,
		WriteTotalTimeoutConstant:   2000,
	}
	return callBool(procSetCommTimeouts, uintptr(handle), uintptr(unsafe.Pointer(&timeouts)))
}

func callBool(proc *syscall.LazyProc, args ...uintptr) error {
	ret, _, errno := proc.Call(args...)
	if ret == 0 {
		if errno != nil && !errors.Is(errno, syscall.Errno(0)) {
			return errno
		}
		return syscall.EINVAL
	}
	return nil
}

func windowsPortPath(name string) string {
	upper := strings.ToUpper(name)
	if strings.HasPrefix(upper, `\\.\`) {
		return name
	}
	if strings.HasPrefix(upper, "COM") {
		return `\\.\` + name
	}
	return name
}

func printPortHint() {
	fmt.Println("pass a serial port with -port, e.g. -port COM3")
}
