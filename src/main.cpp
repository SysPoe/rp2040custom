#include <Arduino.h>

#include <cstring>

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"

#include "dmx_tx.pio.h"

#define DMX_PORTS 4
#define DMX_SLOTS 513
#define DMX_BAUD 250000u
#define FRAME_MAGIC_0 0x44u
#define FRAME_MAGIC_1 0x4du

struct DmxPort {
    PIO pio;
    uint sm;
    uint tx_pin;
    uint en_pin;
    uint offset;
    uint8_t data[DMX_SLOTS];
    uint16_t len;
};

static DmxPort ports[DMX_PORTS] = {
    {.pio = pio0, .sm = 0, .tx_pin = 0, .en_pin = 2},
    {.pio = pio0, .sm = 1, .tx_pin = 4, .en_pin = 6},
    {.pio = pio0, .sm = 2, .tx_pin = 8, .en_pin = 10},
    {.pio = pio0, .sm = 3, .tx_pin = 12, .en_pin = 14},
};

static void dmx_program_init(DmxPort *port) {
    pio_gpio_init(port->pio, port->tx_pin);
    pio_sm_set_consecutive_pindirs(port->pio, port->sm, port->tx_pin, 1, true);

    pio_sm_config c = dmx_tx_program_get_default_config(port->offset);
    sm_config_set_out_pins(&c, port->tx_pin, 1);
    sm_config_set_sideset_pins(&c, port->tx_pin);
    sm_config_set_out_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);

    const float div = (float)clock_get_hz(clk_sys) / (float)(DMX_BAUD * 8u);
    sm_config_set_clkdiv(&c, div);

    pio_sm_init(port->pio, port->sm, port->offset, &c);
    pio_sm_set_pins_with_mask(port->pio, port->sm, 1u << port->tx_pin, 1u << port->tx_pin);
    pio_sm_set_enabled(port->pio, port->sm, true);

    pinMode(port->en_pin, OUTPUT);
    digitalWrite(port->en_pin, HIGH);
}

static void dmx_prepare_break(DmxPort *port) {
    pio_sm_set_enabled(port->pio, port->sm, false);
    pio_sm_clear_fifos(port->pio, port->sm);

    pinMode(port->tx_pin, OUTPUT);
    digitalWrite(port->tx_pin, LOW);
}

static void dmx_finish_break(DmxPort *port) {
    digitalWrite(port->tx_pin, HIGH);

    pio_gpio_init(port->pio, port->tx_pin);
    pio_sm_restart(port->pio, port->sm);
    pio_sm_set_enabled(port->pio, port->sm, true);
}

static void dmx_send_all_ports() {
    uint16_t max_len = 0;
    for (uint i = 0; i < DMX_PORTS; i++) {
        dmx_prepare_break(&ports[i]);
        if (ports[i].len > max_len) {
            max_len = ports[i].len;
        }
    }

    delayMicroseconds(120);

    for (uint i = 0; i < DMX_PORTS; i++) {
        dmx_finish_break(&ports[i]);
    }

    delayMicroseconds(16);

    for (uint16_t slot = 0; slot < max_len; slot++) {
        for (uint port = 0; port < DMX_PORTS; port++) {
            if (slot < ports[port].len) {
                pio_sm_put_blocking(ports[port].pio, ports[port].sm, ports[port].data[slot]);
            }
        }
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

    const uint offset = pio_add_program(pio0, &dmx_tx_program);
    for (uint i = 0; i < DMX_PORTS; i++) {
        ports[i].offset = offset;
        ports[i].data[0] = 0;
        ports[i].len = DMX_SLOTS;
        dmx_program_init(&ports[i]);
    }
}

void loop() {
    handle_usb_frames();
    dmx_send_all_ports();
}
