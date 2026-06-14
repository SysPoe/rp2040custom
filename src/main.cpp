#include <Arduino.h>

#include <cstring>

#include "hardware/gpio.h"
#include "hardware/uart.h"

#define DMX_PORTS 2
#define DMX_SLOTS 513
#define DMX_BAUD 250000u
#define DMX_BREAK_US 176u
#define DMX_MAB_US 32u
#define DMX_MBB_US 0u
#define FRAME_MAGIC_0 0x44u
#define FRAME_MAGIC_1 0x4du

struct DmxPort {
    uart_inst_t *uart;
    uint tx_pin;
    uint en_pin;
    uint8_t data[DMX_SLOTS];
    uint16_t len;
};

static DmxPort ports[DMX_PORTS] = {
    {.uart = uart0, .tx_pin = 0, .en_pin = 2},
    {.uart = uart1, .tx_pin = 4, .en_pin = 6},
};

static void dmx_uart_init(uart_inst_t *uart) {
    uart_init(uart, DMX_BAUD);
    uart_set_format(uart, 8, 2, UART_PARITY_NONE);
    uart_set_fifo_enabled(uart, true);
}

static void dmx_port_init(DmxPort *port) {
    gpio_set_function(port->tx_pin, GPIO_FUNC_UART);
    pinMode(port->en_pin, OUTPUT);
    digitalWrite(port->en_pin, HIGH);
}

static void dmx_send_all_ports() {
    for (uint i = 0; i < DMX_PORTS; i++) {
        uart_tx_wait_blocking(ports[i].uart);
        uart_set_break(ports[i].uart, true);
    }

    delayMicroseconds(DMX_BREAK_US);

    for (uint i = 0; i < DMX_PORTS; i++) {
        uart_set_break(ports[i].uart, false);
    }

    delayMicroseconds(DMX_MAB_US);

    uint16_t pos[DMX_PORTS] = {0};
    uint active_ports = DMX_PORTS;

    while (active_ports > 0) {
        for (uint i = 0; i < DMX_PORTS; i++) {
            DmxPort *port = &ports[i];
            while (pos[i] < port->len && uart_is_writable(port->uart)) {
                uart_putc_raw(port->uart, port->data[pos[i]++]);
            }
        }

        active_ports = 0;
        for (uint i = 0; i < DMX_PORTS; i++) {
            if (pos[i] < ports[i].len) {
                active_ports++;
            }
        }
    }

    for (uint i = 0; i < DMX_PORTS; i++) {
        uart_tx_wait_blocking(ports[i].uart);
    }

    if (DMX_MBB_US > 0) {
        delayMicroseconds(DMX_MBB_US);
    }
}

static void handle_usb_frames() {
    enum ParserState {
        WAIT_MAGIC_0,
        WAIT_MAGIC_1,
        READ_PORT,
        READ_LEN_LO,
        READ_LEN_HI,
        READ_PAYLOAD,
    };

    static ParserState state = WAIT_MAGIC_0;
    static uint8_t port_index = 0;
    static uint16_t len = 0;
    static uint16_t pos = 0;
    static uint8_t scratch[DMX_SLOTS];

    while (Serial.available() > 0) {
        const uint8_t b = (uint8_t)Serial.read();
        switch (state) {
        case WAIT_MAGIC_0:
            state = (b == FRAME_MAGIC_0) ? WAIT_MAGIC_1 : WAIT_MAGIC_0;
            break;
        case WAIT_MAGIC_1:
            state = (b == FRAME_MAGIC_1) ? READ_PORT : WAIT_MAGIC_0;
            break;
        case READ_PORT:
            port_index = b;
            state = READ_LEN_LO;
            break;
        case READ_LEN_LO:
            len = b;
            state = READ_LEN_HI;
            break;
        case READ_LEN_HI:
            len |= (uint16_t)b << 8;
            if (port_index >= DMX_PORTS || len == 0 || len > DMX_SLOTS) {
                state = WAIT_MAGIC_0;
            } else {
                pos = 0;
                state = READ_PAYLOAD;
            }
            break;
        case READ_PAYLOAD:
            scratch[pos++] = b;
            if (pos == len) {
                DmxPort *port = &ports[port_index];
                memcpy(port->data, scratch, len);
                port->len = len;
                Serial.print("OK port=");
                Serial.print(port_index + 1);
                Serial.print(" len=");
                Serial.print(len);
                Serial.print("\r\n");
                state = WAIT_MAGIC_0;
            }
            break;
        }
    }
}

void setup() {
    Serial.begin(115200);

    dmx_uart_init(uart0);
    dmx_uart_init(uart1);

    for (uint i = 0; i < DMX_PORTS; i++) {
        ports[i].data[0] = 0;
        ports[i].len = DMX_SLOTS;
        dmx_port_init(&ports[i]);
    }
}

void loop() {
    handle_usb_frames();
    dmx_send_all_ports();
}
