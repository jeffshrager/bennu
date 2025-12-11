Updated 2025-12-08:

=====================================================================
How I run studies:

LocaL: There is a dir under the repo called 'experiments'. In that are
dirs that are named by the date of the experiment. (And sometimes
including a hint about what that experimenet is about, or something to
uniqueify the name if there are multuiple studies run on the same
day.) All the study materials will end up here, mainly the script
(usually run.sh) and I take a screenshot of where the ship is at the
moment:

https://www.marinetraffic.com/en/ais/details/ships/shipid:5261520) and

Eventually the logs will get stored here and all the analysis will get
done here.

Usually I copy one of the old experiment run.sh scripts to the new
experiment dir and mod it. BE SURE TO CHANGE THE ***** LINES TO HAVE
THE NAME OF THE NEW STUDY *****

Note that the first thing and the last thing that every experiment
should do is to turn the lights off. the way you do that is:

   cd /home/bennu/software/bennu; cp lamp_all_off.config lamp.config

HOWEVER: Most experiments don't end normally -- mostly they are
programmed to run as long as possible, and eventually they come up
against the chronjob reboot (currently every 2 hours).

*********************************************************************
IMPORTANT!!! When your experiment ends, by whatever mechaism, be sure
to do the above, otherwise the lamps will be left in whatever was the
last state when the experiment was stopped, either normally or by
reboot:
   cd /home/bennu/software/bennu; cp lamp_all_off.config lamp.config
*********************************************************************

(FFF Note to future self: Make the demon, or run.py turn all the
lights off!)

Any lamp...config files needed for the study got in ../../ the repo
main src (although maybe this isn't where these should eventually go?)

I open three terminals. One local (to my mac) and two talking on the
remora. The one local runs emacs and is usually just running a shell
located in the experiment dir. The other two are talking to the pi
(via: ssh rome). One of these is going to cd to the current
experiment, e.g.,

  cd /home/bennu/software/bennu/experiments/2025etc

the other will be talking to the repo src main:

  cd /home/bennu/software/bennu

I'll call the top one expterm and the bottom one logterm. The reason
for logterm is that the log files are there, most importantly, the
latest one, which is called lamp_controller.log (and there are likely
to be several backups called lamp_controller.log.1, .2, etc. (again,
these should probably be elsewhere -- there's actually a subdir called
logbkup waiting for them, but log management is a whole other
discussion.)

When I think I'm ready to run, I do this in logterm:

   tail -f lamp_controller.log

In theory run.py is always running because it's a service started by a
demon (or a demon started by a service? ... whatever) and it should
start showing the data being logged.

Then, on expterm I simply:

   source run.sh

The first thing you should see is the ***** line added to the log. If
you don't see this, somethings's immediately wrong. AFter that, make
sure that the experiment seems to be doing what you think it
should. Check that whatever should be happening both in the log and on
the expterm are right. Then you can go to bed, or whatever...except:

*********************************************************************
IMPORTANT!!! When your experiment ends, by whatever mechaism, be sure
to do the above, otherwise the lamps will be left in whatever was the
last state when the experiment was stopped, either normally or by
reboot:
   cd /home/bennu/software/bennu; cp lamp_all_off.config lamp.config
*********************************************************************

Afterwards you're gonna want to locally:

  scp rome:/home/bennu/software/bennu/lamp_controller.log .

and maybe consider gettting all the logs. (Maybe see the "Working with
logs" section for guidance here.)

Finally, you'll want to edit the log to just get the data you want. I
usually create an experiment-specific logged called something like

   Experiment_20251209a.log

that just has the relevant records.

You should plot the data immediately to make sure it looks sane:

   conda activate test
   python3 ../../logplot.py Experiment_20251210.log



Then you'll want to turn this into a tsv for analysis:

   conda activate test
   python3 ../../log2tsv.py Experiment_20251210.log > Experiment_20251210.tsv
   
And you should end up with something that looks like this:

time	methane	windspeed	current
2025-12-10T23:38:14	1.9190001487731934	2.68025	0.3234375
2025-12-10T23:38:19	1.9190001487731934	2.6765625	0.323125
2025-12-10T23:38:24	1.9230000972747803	2.6288125	0.323
2025-12-10T23:38:29	1.9180001020431519	2.6826875	0.3231875
2025-12-10T23:38:35	1.9200000762939453	2.6819375	0.323125
2025-12-10T23:38:40	1.9220000505447388	2.674875	0.323375
2025-12-10T23:38:45	1.9190001487731934	2.6157500000000002	0.323125
2025-12-10T23:38:50	1.9230000972747803	2.5994375	0.322875
2025-12-10T23:38:55	1.9200000762939453	2.6635625000000003	0.323375
2025-12-10T23:39:00	1.9130001068115234	2.6488125	0.3231875
...

=====================================================================
** Connecting to the remora (See ~/howto)

Remember you're running ssh from a machine you ssh'd to, so if you
simpy type ~. you will be disconnected from cataphract and your
connection to the vessel will likely be killed (or may hang around
like a zombie).  To disconnect from the rome trader only you need to
double the tilde to quote it: ~~.

repo is ~/software/bennu

Try opening two shells and in one of them start run.py:

   python3 run.py

and in he other use:

   cp lamp_all_on.config lamp.config 
or cp lamp_all_off.config lamp.config

Save the log locally (or get it in whatever way you like) and run:

   python3 logplot.py [--maw 10] [--mhr 0.25] logfile.log

where maw is moving average window, and mhr is methane half range for
scaling.

Sending commands:

   ssh bennu@relay.bennuclimate.net ssh localhost -p 21965 uptime

=====================================================================
Working with logs:



=====================================================================
** DISCONNECTING AND DISOWNING RUN.PY IF YOU STARTED IT MANUALLY:

^Z
bg
jobs
[find the [#] of the job]
disown -h %#

======================

Methane:

ax.py (axetris reader) tested remotely.

Wind and Current:

 tested remotely.

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



 