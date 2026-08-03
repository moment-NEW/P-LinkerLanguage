#ifndef PL_LINKER_H
#define PL_LINKER_H

#include <stdint.h>

typedef void (*pl_init_fn_t)(void);

typedef struct {
    pl_init_fn_t function;
} pl_init_entry_t;

#define PL_STRINGIFY_IMPL(value) #value
#define PL_STRINGIFY(value) PL_STRINGIFY_IMPL(value)

#if defined(__GNUC__) || defined(__ARMCC_VERSION)
#define PL_USED __attribute__((used))
#define PL_SECTION(name) __attribute__((section(name)))
#else
#define PL_USED
#define PL_SECTION(name)
#endif

/* The layout region named by group collects this section. */
#define PL_INIT(group, priority, function) \
    static const pl_init_entry_t pl_init_##function PL_USED \
    PL_SECTION(".pl.init." PL_STRINGIFY(group) "." PL_STRINGIFY(priority)) = { function }

/* The layout region named by group maps this function to a RAM execution region. */
#define PL_RAMFUNC(group) PL_USED PL_SECTION(".pl.ram_code." PL_STRINGIFY(group))

#endif