import numpy as np
import matplotlib.pyplot as plt
import random
import time

class TurbController: # Abstract class for real-time turbidostat feedback control
    def __init__(self, setpoint=0.0, init_od=1e-6):
        self.output_limits = 0, float('inf')
        self.setpoint = setpoint
        self.od = init_od
        self.state = {'update_time': time.time(), 'od':init_od}
        self.state_history = [self.state]

    def step(self, delta_time=None, od_meas=None, last_transfer_vol_frac=None):
        if delta_time is None: # use real time
            self.state = {'update_time': time.time()}
        else: 
            self.state = {'update_time': self._last_time() + delta_time}
        delta_time = self.state['update_time'] - self._last_time()
        #if od_meas:
        #    self.od = od_meas
        transfer_vol_frac = self._step(delta_time, od_meas, last_transfer_vol_frac)
        # limit output
        min_out, max_out = self.output_limits
        transfer_vol_frac = min(max_out, max(min_out, transfer_vol_frac))
        self.state.update({'od':self.od, 'delta_time':delta_time, 'output':transfer_vol_frac})
        self.state_history.append(self.state)
        return transfer_vol_frac

    def _step(self, delta_time, od_meas, last_transfer_frac=None):
        #last_transfer_frac: allow override of last command used in calculations with report of what system actually did
        pass
    
    def _last_time(self):
        return self.state_history[-1]['update_time']

    def history(self):
        return self.state_history[1:] if self.state_history else [] # omit initial state

    def scrape_history(self, key, fill_value = None):
        return [state.get(key, fill_value) for state in self.history()]

    def __call__(self, *args, **kwargs):
        return self.step(None, *args, **kwargs) # default to real time


class ParamEstTurbCtrlr(TurbController):
    def __init__(self, setpoint=0.0, init_od=1e-6, init_k=None):
        super(ParamEstTurbCtrlr, self).__init__(setpoint, init_od)
        self.default_k = 1.8
        if init_k is None:
            init_k = self.default_k
        self.k_estimate = init_k
        self.state.update({'k_estimate': init_k})
        self.k_limits = .05, 5

    def predict_od(self, od_now, transfer_vol_frac, dt, k):
        # delta time (dt) is in seconds, k is in hr^-1
        return od_now*np.exp(dt/3600*k)/(1+transfer_vol_frac)

    def infer_k(self, od_then, transfer_vol_frac, od_now, dt):
        min_k, max_k = self.k_limits
        return max(min_k, min(max_k, np.log((transfer_vol_frac + 1)*od_now/od_then)/dt*3600))

    def _step(self, delta_time, od_meas, last_transfer_frac=None):
        last_state = self.state_history[-1]
        prior_od = last_state.get('od', self.od)
        prior_out = last_state.get('output', 0) if last_transfer_frac is None else last_transfer_frac
        prior_k = last_state.get('k_estimate', self.default_k)
        if od_meas is not None:
            prediction = self.predict_od(prior_od, prior_out, delta_time, prior_k)
            self.od = od_meas # max(prediction - .05, min(prediction + .05, od_meas)) # clamp based on prediction to rule out crazy readings
        #error = self.predict_od(prior_od, prior_out, delta_time, prior_k) - od_meas
        s = .15
        self.k_estimate = prior_k*(1-s) + self.infer_k(prior_od, prior_out, self.od, delta_time)*s
        # try to close a fraction of the distance to the correct volume per iteration
        # use model to solve for perfect transfer volume, which may not be achievable
        s = .7
        transfer_vol_frac = (self.od*np.exp(delta_time/3600*self.k_estimate)
                    /((self.setpoint*s + prior_od*(1-s))) - 1)
        # limit output
        min_out, max_out = self.output_limits
        transfer_vol_frac = min(max_out, max(min_out, transfer_vol_frac))
        self.state.update({'k_estimate':self.k_estimate})
        return transfer_vol_frac

    def set_od(self, od):
        self.od = od

if __name__ == '__main__':
    pass

