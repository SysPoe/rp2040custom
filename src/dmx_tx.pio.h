// Checked-in output equivalent to src/dmx_tx.pio.
// PlatformIO's Arduino RP2040 flow used here does not run pioasm automatically.

#pragma once

#if !PICO_NO_HARDWARE
#include "hardware/pio.h"
#endif

#define dmx_tx_wrap_target 0
#define dmx_tx_wrap 5

static const uint16_t dmx_tx_program_instructions[] = {
    0x98a0, // 0: pull   block       side 1
    0xf727, // 1: set    x, 7        side 0 [7]
    0x6601, // 2: out    pins, 1            [6]
    0x0042, // 3: jmp    x--, 2
    0xbe42, // 4: nop                side 1 [6]
    0xbe42, // 5: nop                side 1 [6]
};

#if !PICO_NO_HARDWARE
static const struct pio_program dmx_tx_program = {
    .instructions = dmx_tx_program_instructions,
    .length = 6,
    .origin = -1,
};

static inline pio_sm_config dmx_tx_program_get_default_config(uint offset) {
    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_wrap(&c, offset + dmx_tx_wrap_target, offset + dmx_tx_wrap);
    sm_config_set_sideset(&c, 1, true, false);
    return c;
}
#endif
