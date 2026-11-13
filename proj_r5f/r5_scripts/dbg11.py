import pickle,json,os,sys
ROOT='/workspace/thesis/proj_r5d'; sys.path.insert(0,ROOT+'/src'); os.chdir(ROOT)
from tdr.config import PhysicalConfig
from tdr.data import load_instance
from tdr.replay import verify_replay
pkg=json.load(open('data/package_light.json')); phys=PhysicalConfig.from_dict(dict(pkg['config']))
inst=load_instance(pkg,'RC100'); phys=phys.for_case(pkg.get('case_fleet'),'RC100')
d=pickle.load(open('/tmp/inv_rc100_4.pkl','rb'))
r=verify_replay(inst,phys,d['segments']); print('replay',r.ok,r.violations[:5])
