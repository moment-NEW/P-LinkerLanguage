#ifndef PL_LINKER_LAYOUT_H
#define PL_LINKER_LAYOUT_H

#include <stdint.h>

typedef enum {
    PL_MEMORY_RX = 0x1,
    PL_MEMORY_RW = 0x2,
    PL_MEMORY_RWX = PL_MEMORY_RX | PL_MEMORY_RW,
} pl_memory_attributes_t;

typedef enum {
    PL_LINK_INIT,
    PL_LINK_RAM_CODE,
    PL_LINK_RESERVED,
} pl_link_kind_t;

typedef struct {
    const char *name;
    uint64_t origin;
    uint64_t size;
    pl_memory_attributes_t attributes;
} pl_memory_t;

typedef struct {
    const char *name;
    pl_link_kind_t type;
    const char *memory;
    const char *load_memory;
    uint64_t address;
    uint64_t size;
    uint32_t alignment;
    const char *start_symbol;
    const char *end_symbol;
    const char *load_symbol;
} pl_link_region_t;

#define PL_AUTO UINT64_MAX
#define PL_LINKER_SIZE (UINT64_MAX - 1U)
#define PL_NO_MEMORY ((const char *)0)
#define PL_NO_SYMBOL ((const char *)0)
#define PL_KIB(value) ((uint64_t)(value) * 1024U)
#define PL_MIB(value) ((uint64_t)(value) * 1024U * 1024U)
#define PL_REF(name) #name
#define PL_SYMBOL(name) #name

#endif