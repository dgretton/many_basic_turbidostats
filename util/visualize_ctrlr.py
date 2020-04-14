from turbsim import SimTurbidostat, ParamEstTurbCtrlr
import matplotlib.pyplot as plt
import random

xs = sim_turbs = ods = None
n_turbs = 24

def reinit():
    global xs, sim_turbs, ods
    xs = []
    ods = [i/n_turbs*.4 + .01 for i in range(n_turbs)]
    sim_turbs = [SimTurbidostat(ParamEstTurbCtrlr(), 20*60, setpoint=.45, init_od=od) for od in ods]

def plotem():
    od_courses = [st.controller.scrape_history('od') for st in sim_turbs]
    output_courses = [st.controller.scrape_history('output') for st in sim_turbs]
    k_est_courses = [st.controller.scrape_history('k_estimate') for st in sim_turbs]

    for odcs, opcs in zip(od_courses, output_courses):
        plt.plot(odcs, opcs)
    plt.figure()
    plt.gca().set_prop_cycle(None)
    plt.plot(xs, list(zip(*k_est_courses)))
    plt.figure()
    plt.gca().set_prop_cycle(None)
    plt.plot(xs, list(zip(*od_courses)))
    plt.figure()
    plt.gca().set_prop_cycle(None)
    plt.plot(xs, list(zip(*output_courses)))
    plt.show()

reinit()
for turb in sim_turbs:
    turb.controller.output_limits = 0, 1
    turb.set_k(.1+random.random()*1.5)
    #turb.set_k(1.8)
for t in range(100):
    for turb, od in zip(sim_turbs, ods):
        turb.update()
    xs.append(t)
if True:#False:
    newod = .3
    for turb in sim_turbs:
        turb.controller.setpoint = newod
    for t in range(100, 200):
        for turb, od in zip(sim_turbs, ods):
            turb.update()
        xs.append(t)
    newod = .8
    for turb in sim_turbs:
        turb.controller.setpoint = newod
    for t in range(200, 300):
        for turb, od in zip(sim_turbs, ods):
            turb.update()
        xs.append(t)
plotem()
