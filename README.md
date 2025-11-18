Updated Monday PM(PST) 2025-11-17:

Methane:

ax.py (axetris reader) was tested by Jeff just before the LampRay was
shipped.

Wind and Current:

Wind and Current Sensor code are now in the same .sh file. Wind was
tested by Jeff (in its original separate form), but he (Jeff) wasn't
able to get current to read anything but 0s. Since this code looks
identical, either the jumpering on the board was bad when Jeff tested
it, or these have to be run in sequence (which Jeff didn't try).

Quad lamp control:

A quad is 1/4 of the LampRay (or, in metric, 0.00635ths of it). The
tube as a bow and stern (which, n.b. !!, is how it's supposed to be
put on the ship), and then a port and starboard, so: (BP SP BS
SS). The actual lamp module numbering would be relevant, but it's not
now.

The lamps are on GPIO pins 16,23,24,25 (I hope), so we need to at some
point figure out the mapping between these and the (BP SP BS
SS). (This can almost be figured entirely remotely, but we should just
look into the thing when it's being setup!) 

The INCORRECT (but works -- sort of) way that I originally tested
these was using:

  gpioset GPIO16=1

This turns ON one of the quads (raises pin 16). HOWEVER, it
hangs. This is actually by design of the gpioset program. The way I
originally worked the quads was using the above to turn them on, then
^c'ing out (which left the pin/quad on), and then using:

  gpioget GPIO16

that turned it off. However, what was really happening (because I
didn't understand these commands at the time) was that gpioget puts
the pin in read mode, which unsets the 1 left there by gpioset, and
then reads from it, so the turning off this was a side effect.

Old multi-lamps control:

lamps.py and remora_config.csv were intended to run the old separate
lamp config. They are no longer functional, and never really worked
right anyway.

gpio-hold-off.sh, gpio-hold-on.sh, and gpio-hold-status.sh were
intended to set lamps on or off and return, and keep a log file of the
transitions. The log file is supposed to be in a .pid file in the base
(/run/gpiohold) and metadata file (.meta) and a .log file. and the
...state would read these for reporting. Unfortunately, this was all
coded by chatgpt and never tested, and I think doesn't work. Also,
it's over complex. (Note that we don't use a chip ID, and I don't know
if you can even give one. Anyway, once we know that the quads actually
work someone can fix this code.



 