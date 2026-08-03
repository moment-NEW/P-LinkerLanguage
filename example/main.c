#include <stdint.h>

#include "pl_linker.h"
#include "pl_linker_symbols.h"

static void board_init(void)
{
    /* Configure clocks and pins. */
}

static void driver_init(void)
{
    /* Start peripheral drivers. */
}

PL_INIT(app_init, 010, board_init);
PL_INIT(app_init, 020, driver_init);

PL_RAMFUNC(fast_code)
void motor_control_step(void)
{
    /* This function executes from RAM after startup copies FAST_CODE. */
}

void pl_run_app_initializers(void)
{
    const pl_init_entry_t *entry;

    for (entry = pl_app_init_start; entry < pl_app_init_end; ++entry) {
        entry->function();
    }
}

void pl_copy_fast_code(void)
{
    uint8_t *destination = pl_fast_code_start;
    const uint8_t *source = pl_fast_code_load_start;

    while (destination < pl_fast_code_end) {
        *destination++ = *source++;
    }
}