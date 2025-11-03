from gpiozero import DigitalOutputDevice
from time import sleep
from dataclasses import dataclass

ldata = DigitalOutputDevice(13, initial_value = False)
lclk = DigitalOutputDevice(6, initial_value=False)
lenable = DigitalOutputDevice(19, initial_value=False)
lstrobe = DigitalOutputDevice(26, initial_value=False)

lstate: int = 0
masks = [0x3f]  # list of binary (hex) values to mask into state
boards = [0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]  # list of state value of each board, 1 = all lamps on, 0 = none 
masksr = []   #


def gen_masks():
    global masksr, masks
    
    m = 0x3f
    for _ in range(19):   # 1st one is already there
        m = m << 6
        masks.append(m)
        
    masks_revi = reversed(masks)
    masksr = list(masks_revi)
    print("masksr len: ", len(masksr))
    
    
@dataclass
class Lampclk:
    """ run the Lamp Clock """
    # Set up pulsewidth
    delay: float = .05  # seconds
    
    def runclk(self, cnt : int) -> None:
        for _ in range(cnt):
            lclk.on()
            sleep(self.delay)
            lclk.off()


def LampsData(len : int, dataval : int):
    """ Data and signal handshakes for serial lamp data"""
    
    #len : int # length in bits
    #dataval : int #  Actual data in binary (shown in hex)+
    
    lstrobe.on()
    for i in range(len):
        d = dataval & 0x00001
            
        if d == 0:
            ldata.off()
        else:
            ldata.on()

        lamps.runclk(1)  # clock in the value
            
        dataval = dataval >> 1
            
    lstrobe.off()
    sleep(.1)
        
    lenable.on()

        
def LampsAllOn(len: int):
    """ Data and signal handshakes for serial lamp data when all lamps ON"""
    
    #len : int # length in bits
    # All data will be 1
    
    lstrobe.on()
    for i in range(len):
        
        ldata.on()
        lamps.runclk(1)  # clock in the value
                        
    lstrobe.off()
    sleep(.1)
        
    lenable.on()
    sleep(.1)
    lenable.off()
    
    
    
def LampsAllOff(len:int):
    """ Data and signal handshakes for serial lamp data when all lamps ON"""
    
    #len : int # length in bits
    # All data will be 0
    
    #  save the state bits and board list items
    astate = 0
    for b, m in enumerate(masks):
        boards[b] = 0
        
    print("all off: astate: ",hex(astate))
    lstrobe.on()
    
    for _ in range(len):        
        ldata.off()
        lamps.runclk(1)  # clock in the value
                       
    lstrobe.off()
    sleep(.1)
        
    lenable.off()   

    
def calc_all_on_state():
    astate = 0
    for b, m in enumerate(masks):
        astate = astate | m
        boards[b] = 1
        
    # print("astate: ",hex(astate))
    return astate
        

def board_on(val):
    boards[val] = 1
    state = 0
    state = state | masksr[val]
    print("state :", hex(state), boards)
    LampsData(120, state)

# for i in range(100000):
    # LampsAllOn(6)
    # sleep(.2)
    # LampsAllOff(6)
    # sleep(.2)

#LClkSerial(6,0x000)


# #############################################
# #### Start Scripts Here
gen_masks()
allstate = calc_all_on_state()

# print( len(masks), len(masksr),hex(masks[0]), hex(masks[1]), hex(masks[19]))

# Create a Lampclk object
lamps = Lampclk(.01)
    
LampsAllOff(120)

#LampsData(120, allstate)
#sleep(3)
board_on(1)
sleep(3)
state = masksr[0] | masksr[3] | masksr[19]
print("state1 :", hex(state))
LampsData(120, state)
sleep(8)
#LampsData(120, 0x3F000)
sleep(3)
LampsAllOff(120)




# Stuff that worked before
# LampsData(6,0x3ff)
#LampsData(12,0)
#sleep(2)
#LampsData(12,0x88)
#LampsData(12,0)
#LampsAllOff(12)

                                                         




































