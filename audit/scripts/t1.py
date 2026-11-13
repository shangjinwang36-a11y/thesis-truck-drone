from capture import *
for conf,case in [('spec','C50'),('light','C50')]:
    for seed in range(1,11):
        w=HiddenWorld(load_instance(setup(conf)[0],case),case,seed)
        print(conf,case,seed,w.configured_failure_count)
