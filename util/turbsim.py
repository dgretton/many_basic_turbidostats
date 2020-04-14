import os
import sys
turb_ctrl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if turb_ctrl_path not in sys.path:
    sys.path.append(turb_ctrl_path)

from turb_control import ParamEstTurbCtrlr
import numpy as np
import matplotlib.pyplot as plt
import random
import time
import threading

class SimTurbidostat:
    def __init__(self, controller, cycle_time, setpoint=0.0, init_od=0.0, growth_k=2.08): # commonly cited double every 20 minutes
        self.cycle_time = cycle_time # in seconds
        self.growth_k = growth_k # ground truth k (hrs^-1), different from controller k estimate
        self.od = init_od # ground truth od, different from controller od
        controller.output_limits = .05, .68
        controller.setpoint = setpoint
        self.controller = controller
        self.wait_thread = None

    def update(self, realtime=False):
        if self.wait_thread: # use threading for delays to allow multiple simultaneous real-time simulations
            self.wait_thread.join()
        # grow culture
        self.od = self.od*np.exp(self.cycle_time/3600*self.growth_k)
        delta_time = None if realtime else self.cycle_time
        meas_noise = 1/(1+random.random()*10000) # Occasional very large spikes, as when clumps occlude sensor
        if delta_time:
            transfer_vol_frac = self.controller.step(delta_time, self.od + meas_noise)
        else:
            transfer_vol_frac = self.controller(self.od + meas_noise) # exercise callable functionality
        # add mechanical/operational noise
        actual_transfer_vol_frac = transfer_vol_frac + (random.random()*2-1)*.02
        # dilute according to command
        self.od = self.od/(1+actual_transfer_vol_frac)
        if realtime:
            self.wait_thread = threading.Thread(target=lambda: time.sleep(cycle_time))
            self.wait_thread.start() 

    def set_k(self, k):
        self.growth_k = k

    def set_od(self, od):
        self.od = od

def rand_between(a, b):
    return min(a,b) + random.random()*abs(b-a)

realtime = sys.argv[1] == '--realtime' if len(sys.argv) > 1 else False

if __name__ == '__main__':
    normal_cycle_time = 30*60 # 30 mins in seconds
    if realtime:
        cycle_time = .1
    else:
        cycle_time = normal_cycle_time

    xs = []
    sim_turbs = [SimTurbidostat(ParamEstTurbCtrlr(), cycle_time) for _ in range(24)]

    def get_history(turb, key):
        return [state.get(key, 0) for state in turb.controller.history()]

    def plotem():
        od_courses, output_courses, k_courses = ([st.controller.scrape_history(key) for st in sim_turbs] for key in ('od', 'output', 'k_estimate'))
        print(k_courses)
        plt.plot(xs, list(zip(*od_courses)))
        plt.figure()
        plt.plot(xs, list(zip(*output_courses)))
        plt.figure()
        plt.plot(xs, list(zip(*k_courses)))
        plt.show()

    for w, sim_turb in enumerate(sim_turbs):
        sim_turb.setpoint = .8
        sim_turb.set_od(rand_between(.1*.66, .8*.66))
        scale = normal_cycle_time*10 if realtime else 1
        if realtime:
            sim_turb.controller.k_limits = .05, 25000
        sim_turb.set_k(rand_between(.92*scale, .93*scale))
        # if w < 12:
        #     sim_turb.set_k(rand_between(1.3*scale, 1.5*scale))
        # else:
        #     sim_turb.set_k(rand_between(1.8*scale, 2.08*scale))

    for i in range(100 if realtime else 200):
        try:
            xs.append(i*normal_cycle_time/3600)
            tooth_size = 40
            if i % tooth_size == 0:
                tooth_height = .02+rand_between(0,.06)
                for w, sim_turb in enumerate(sim_turbs):
                    sim_turb.controller.setpoint = (i%(tooth_size*2)/tooth_size)*tooth_height+.8
                    print((i%(tooth_size*2)/tooth_size)*tooth_height+.4)
            for sim_turb in sim_turbs:
                sim_turb.update(realtime=realtime)
            print('cycle:', i)
            #time.sleep(cycle_time/sim_time_dilation)
        except KeyboardInterrupt:
            import pdb; pdb.set_trace()

    plotem()
