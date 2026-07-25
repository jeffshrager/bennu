#!/bin/bash
cd "$(dirname "$0")"
python3 exprun.py '[5,1000,4000,off]' '[6,500,2000,on]'
