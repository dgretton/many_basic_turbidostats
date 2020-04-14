#!python3

import sys, os, time, logging, sqlite3
import types
import pdb
from turb_control import ParamEstTurbCtrlr

this_file_dir = os.path.dirname(os.path.abspath(__file__))
method_local_dir = os.path.join(this_file_dir, 'method_local')
containing_dirname = os.path.basename(os.path.dirname(this_file_dir))

from pace_util import (
    pyhamilton, LayoutManager, ResourceType, Plate96, Plate24, Tip96,
    HamiltonInterface as HI, ClarioStar, LBPumps as Pumps, PlateData, Shaker,
    initialize, hepa_on, tip_pick_up, tip_eject, aspirate, dispense, wash_empty_refill,
    tip_pick_up_96, tip_eject_96, aspirate_96, dispense_96,
    resource_list_with_prefix, read_plate, move_plate, add_robot_level_log, add_stderr_logging,
    fileflag, clear_fileflag, run_async, yield_in_chunks, log_banner)

class Timer:
    def __init__(self):
        self.start_time = 0
        self.duration = 0

    def start(self, duration):
        self.start_time = time.time()
        self.duration = duration

    def wait(self):
        if simulation_on:
            return
        while time.time() - self.start_time < self.duration:
            time.sleep(.1)

def ensure_meas_table_exists(db_conn):
    '''
    Definitions of the fields in this table:
    lagoon_number - the number of the lagoon, uniquely identifying the experiment, zero-indexed
    filename - absolute path to the file in which this data is housed
    plate_id - ID field given when measurement was requested, should match ID in data file
    timestamp - time at which the measurement was taken
    well - the location in the plate reader plate where this sample was read, e.g. 'B2'
    measurement_delay_time - the time, in minutes, after the sample was pipetted that the
                            measurement was taken. For migration, we consider this to be 0
                            minutes in the absense of pipetting time values
    reading - the raw measured value from the plate reader
    data_type - 'lum' 'abs' or the spectra values for the fluorescence measurement
    '''
    c = db_conn.cursor()
    c.execute('''CREATE TABLE if not exists measurements
                (lagoon_number, filename, plate_id, timestamp, well, measurement_delay_time, reading, data_type)''')
    db_conn.commit()

def db_add_plate_data(plate_data, data_type, plate, vessel_numbers, read_wells):
    db_conn = sqlite3.connect(os.path.join(method_local_dir, containing_dirname + '.db'))
    ensure_meas_table_exists(db_conn)
    c = db_conn.cursor()
    for lagoon_number, read_well in zip(vessel_numbers, read_wells):
        filename = plate_data.path
        plate_id = plate_data.header.plate_ids[0]
        timestamp = plate_data.header.time
        well = plate.position_id(read_well)
        measurement_delay_time = 0.0
        reading = plate_data.value_at(*plate.well_coords(read_well))
        data = (lagoon_number, filename, plate_id, timestamp, well, measurement_delay_time, 
                 reading, data_type)
        c.execute("INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?)", data)
    db_conn.commit()
    db_conn.close()

sys_state = types.SimpleNamespace()
# define system state
sys_state.instruments = None
sys_state.need_to_refill_washer = True
sys_state.need_to_read_plate = False
sys_state.mounted_tips = None
method_start_time = None

cycle_time = 15*60 # 15 minutes
wash_vol = 250
max_transfer_vol = 985 # uL
read_sample_vol = 75 # uL
generation_time = 30 * 60 # seconds
fixed_turb_height = 8 # mm
turb_vol = 1430 # uL
desired_od = .45
fly_disp_height = fixed_turb_height + 9 # mm
shake_speed = 300

sys_state.disable_pumps = '--no_pumps' in sys.argv
debug = '--debug' in sys.argv
simulation_on = debug or '--simulate' in sys.argv
mid_run = '--continue' in sys.argv

sys_state.waffle_clean_thread = None

def HamiltonInterface():
    return HI(simulate=simulation_on)

layfile = os.path.join(this_file_dir, 'assets', 'deck.lay')
lmgr = LayoutManager(layfile)

# deck locations
turb_plate = lmgr.assign_unused_resource(ResourceType(Plate24, 'turbs'))
media_reservoir = lmgr.assign_unused_resource(ResourceType(Plate96, 'waffle'))
reader_tray = lmgr.assign_unused_resource(ResourceType(Plate96, 'reader_tray_00001'))
reader_plate = lmgr.assign_unused_resource(ResourceType(Plate96, 'reader_plate'))
bleach_site = (#lmgr.assign_unused_resource(ResourceType(Tip96, 'RT300_HW_96WashDualChamber1_bleach')) TODO
            lmgr.assign_unused_resource(ResourceType(Tip96, 'RT300_HW_96WashDualChamber1_water'))) #original rinse_site
disp_tips = resource_list_with_prefix(lmgr, 'disposable_tips_', Tip96, 1) #TODO: only one box?
wash_tips = lmgr.assign_unused_resource(ResourceType(Tip96, 'wash_tips'))

#plate_trash = lmgr.assign_unused_resource(ResourceType(Plate96, 'plate_trash'))

def system_initialize():
    ham_int, reader_int, reader_int, shaker, *_ = sys_state.instruments
    if mid_run:
        print('CONTINUING A PREVIOUSLY INITIALIZED AND PAUSED RUN. WILL SKIP CLEANING. OK? 5 SECONDS TO CANCEL...')
        time.sleep(5)
    local_log_dir = os.path.join(method_local_dir, 'log')
    if not os.path.exists(local_log_dir):
        os.mkdir(local_log_dir)
    main_logfile = os.path.join(local_log_dir, 'main.log')
    logging.basicConfig(filename=main_logfile, level=logging.DEBUG, format='[%(asctime)s] %(name)s %(levelname)s %(message)s')
    add_robot_level_log()
    add_stderr_logging()
    for banner_line in log_banner('Begin execution of ' + __file__):
        logging.info(banner_line)
    if sys_state.disable_pumps or simulation_on:
        pump_int.disable()
    if simulation_on:
        reader_int.disable()
        shaker.disable()
    ham_int.set_log_dir(os.path.join(local_log_dir, 'hamilton.log'))
    if mid_run:
        prime_and_clean = None
    else:
        prime_and_clean = run_async(lambda: (#pump_int.prime(),             # important that the shaker is
            shaker.start(shake_speed), pump_int.bleach_clean(),
            shaker.stop())) # started and stopped at least once
    initialize(ham_int)
    hepa_on(ham_int, simulate=int(simulation_on))
    method_start_time = time.time()
    if not sys_state.disable_pumps:
        wash_empty_refill(ham_int, refillAfterEmpty=2, chamber2WashLiquid=0) # 2=chamber 1 only; 0=Liquid 1 (bleach)
    if prime_and_clean:
        prime_and_clean.join()
    shaker.start(shake_speed) # TODO: For asynchrony

def flow_rate_controller():
    min_flow_through = (read_sample_vol + 30)/turb_vol
    max_flow_through = max_transfer_vol/turb_vol
    controller = ParamEstTurbCtrlr(setpoint=desired_od)
    controller.output_limits = min_flow_through, max_flow_through
    return controller

def disp_tips_gen():
    while True:
        for disp_tip_rack in disp_tips:
            for i in range(72): # TODO: This is to reset the tip usage so that the same tips have the same roles each iteration so we can get away with reuse(0, 96):
                yield disp_tip_rack, i
disp_tips_gen = disp_tips_gen()

def new_tips():
    ham_int, reader_int, reader_int, shaker, *_ = sys_state.instruments
    while True:
        try:
            positions =[next(disp_tips_gen) for i in range(8)] 
            tip_pick_up(ham_int, positions)
            return positions
        except pyhamilton.TipPresentError:
            tip_eject(ham_int)
        except pyhamilton.NoTipError:
            pass

batches = (range(8), range(8, 16), range(16, 24))

def sample_turbs():
    ham_int, reader_int, reader_int, shaker, *_ = sys_state.instruments
    #shaker.stop() TODO: for asynchrony
    for batch in batches:
        tip_poss = new_tips()
        aspirate(ham_int, [(turb_plate, i) for i in batch], [read_sample_vol]*8)
        dispense(ham_int, [(reader_plate, i) for i in batch], [read_sample_vol]*8)
        tip_eject(ham_int, tip_poss)
    #shaker.start(shake_speed) TODO: for asynchrony

def read_ods():
    ham_int, reader_int, reader_int, shaker, *_ = sys_state.instruments
    abs_platedata, = read_plate(ham_int, reader_int, reader_tray, reader_plate, ['17_8_12_abs'], 'turb_read_plate')
    if not abs_platedata:
        abs_platedata = PlateData(os.path.join('assets', 'dummy_platedata.csv')) # sim dummies
    list_24 = list(range(24))
    db_add_plate_data(abs_platedata, 'abs', reader_plate, list_24, list_24)
    readings = []
    for i in range(24):
        data_val = abs_platedata.value_at(*reader_plate.well_coords(i))
        od = 5.40541*data_val - 0.193514 # empirical best fit line https://docs.google.com/spreadsheets/d/1Fc5jwPgzb_UN-tldBs_IeWo4Yve6KrvkIpQyVNIYQ8U/edit?usp=sharing
        readings.append(od)
    logging.info("CONVERTED OD READINGS " + str(readings))
    return readings

controllers = [flow_rate_controller() for _ in range(24)]

def transfer_function(readings):
    flow_rates = [controller(reading) for controller, reading in zip(controllers, readings)] # step (__call__()) all controllers
    logging.info("FLOW RATES " + str(flow_rates))
    logging.info("K ESTIMATES " + str([controller.k_estimate for controller in controllers]))
    logging.info("OD ESTIMATES " + str([controller.od for controller in controllers]))
    replace_vols = [rate*turb_vol for rate in flow_rates]
    logging.info("REPLACEMENT VOLUMES " + str(replace_vols))
    return replace_vols

def replace_media(replace_vols):
    ham_int, reader_int, reader_int, shaker, *_ = sys_state.instruments
    if sys_state.waffle_clean_thread:
        sys_state.waffle_clean_thread.join()
    pump_int.refill(30)
    shaker.stop()
    for batch in batches:
        tip_poss = new_tips()
        aspirate(ham_int, [(media_reservoir, i%8) for i in batch], [replace_vols[i] for i in batch])
        dispense(ham_int, [(turb_plate, i) for i in batch], [replace_vols[i] for i in batch], liquidHeight=fly_disp_height, dispenseMode=9)
        shaker.start(shake_speed)
        tip_eject(ham_int, tip_poss) #TODO: only for tip reuse
        tip_poss = new_tips() #TODO: only for tip reuse
        shaker.stop()
        aspirate(ham_int, [(turb_plate, i) for i in batch], [800]*8, liquidHeight=fixed_turb_height)
        dispense(ham_int, [(bleach_site, i%8 + 88) for i in batch], [800]*8, liquidHeight=15) # +88 for far right side of bleach
        tip_eject(ham_int, tip_poss)
    shaker.start(shake_speed)

def system_clean():
    ham_int, reader_int, reader_int, shaker, *_ = sys_state.instruments
    sys_state.waffle_clean_thread = run_async(pump_int.bleach_clean)
    tip_pick_up_96(ham_int, wash_tips)
    for i in range(2):
        aspirate_96(ham_int, bleach_site, wash_vol)
        dispense_96(ham_int, reader_plate, wash_vol)
        aspirate_96(ham_int, reader_plate, wash_vol + read_sample_vol, mixVolume=wash_vol, mixCycles=2)
        dispense_96(ham_int, bleach_site, wash_vol + read_sample_vol)
    tip_eject_96(ham_int, wash_tips)
    if not sys_state.disable_pumps:
        wash_empty_refill(ham_int, refillAfterEmpty=2, chamber2WashLiquid=0) # 2=chamber 1 only; 0=Liquid 1 (bleach)


def main():
    timer = Timer()
    while True:
        timer.start(cycle_time)
        sample_turbs()
        readings = read_ods()
        replace_volumes = transfer_function(readings)
        replace_media(replace_volumes)
        system_clean()
        timer.wait()

class Nothing:
    def __init__(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

if __name__ == '__main__':
    with HamiltonInterface() as ham_int, \
            ClarioStar() as reader_int, \
            LBPumps() as pump_int:
        sys_state.instruments = ham_int, reader_int, pump_int
        system_initialize()
        main()
    