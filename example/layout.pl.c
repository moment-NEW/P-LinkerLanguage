#include "pl_linker_layout.h"

/* The tokenizer keeps exactly one branch. The structure model stays backend-neutral. */
#if defined(PL_TOOLCHAIN_GNU)
const char *const pl_demo_active_backend = "gnu";
#elif defined(PL_TOOLCHAIN_ARMCLANG)
const char *const pl_demo_active_backend = "armclang";
#else
#error A linker backend must be selected
#endif

const pl_memory_t pl_memories[] = {
    {
        .name = "FLASH",
        .origin = 0x08000000,
        .size = PL_KIB(512),
        .attributes = PL_MEMORY_RX,
    },
    {
        .name = "RAM",
        .origin = 0x20000000,
        .size = PL_KIB(128),
        .attributes = PL_MEMORY_RWX,
    },
};

const pl_link_region_t pl_regions[] = {
    {
        .name = "app_init",
        .type = PL_LINK_INIT,
        .memory = PL_REF(FLASH),
        .load_memory = PL_REF(FLASH),
        .address = PL_AUTO,
        .size = PL_LINKER_SIZE,
        .alignment = 4,
        .start_symbol = PL_SYMBOL(pl_app_init_start),
        .end_symbol = PL_SYMBOL(pl_app_init_end),
        .load_symbol = PL_NO_SYMBOL,
    },
    {
        .name = "fast_code",
        .type = PL_LINK_RAM_CODE,
        .memory = PL_REF(RAM),
        .load_memory = PL_REF(FLASH),
        .address = PL_AUTO,
        .size = PL_LINKER_SIZE,
        .alignment = 4,
        .start_symbol = PL_SYMBOL(pl_fast_code_start),
        .end_symbol = PL_SYMBOL(pl_fast_code_end),
        .load_symbol = PL_SYMBOL(pl_fast_code_load_start),
    },
    {
        .name = "shared_buffer",
        .type = PL_LINK_RESERVED,
        .memory = PL_REF(RAM),
        .load_memory = PL_NO_MEMORY,
        .address = 0x2001E000,
        .size = PL_KIB(8),
        .alignment = 32,
        .start_symbol = PL_SYMBOL(pl_shared_buffer_start),
        .end_symbol = PL_SYMBOL(pl_shared_buffer_end),
        .load_symbol = PL_NO_SYMBOL,
    },
};