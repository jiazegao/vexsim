In a real PROS project this folder holds precompiled ARM libraries: the kernel's
(`libpros.a`, ...) and LemLib's (`LemLib.a`). They can't run on a PC, so
`vexsim build` ignores this folder and builds LemLib from source instead.
