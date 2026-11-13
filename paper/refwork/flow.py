import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch
import glob
for f in glob.glob('/usr/share/fonts/opentype/noto/*CJK*'):
    fm.fontManager.addfont(f)
names=[f.name for f in fm.fontManager.ttflist if 'CJK SC' in f.name]
plt.rcParams['font.family']=sorted(set(names))[0] if names else 'sans-serif'
fig,ax=plt.subplots(figsize=(9.5,12.5)); ax.set_xlim(0,100); ax.set_ylim(0,130); ax.axis('off')
def box(x,y,w,h,t,fc='#eef3fb',ec='#2f4b7c',fs=10.5,dashed=False):
    ax.add_patch(FancyBboxPatch((x-w/2,y-h/2),w,h,boxstyle='round,pad=0.6',fc=fc,ec=ec,lw=1.3,ls='--' if dashed else '-'))
    ax.text(x,y,t,ha='center',va='center',fontsize=fs,wrap=True)
def arr(x1,y1,x2,y2,t=None,off=(1.5,0)):
    ax.annotate('',xy=(x2,y2),xytext=(x1,y1),arrowprops=dict(arrowstyle='->',lw=1.2,color='#333'))
    if t: ax.text((x1+x2)/2+off[0],(y1+y2)/2+off[1],t,fontsize=9,color='#444')
# nominal
box(50,120,62,5,'输入：算例、物理参数、算法配置（不含隐藏环境）')
box(50,111,62,6,'名义阶段：全地送初解（扇区+最近邻）→ 空送转换启动\n→ ALNS 优化（1000 次完整评价）→ 独立核验',fc='#e8f5e9',ec='#2e7d32')
box(50,102,62,5,'固定名义计划，确定班次时限 H = max F_k + 1800 s',fc='#e8f5e9',ec='#2e7d32')
box(50,93,62,5,'执行仿真：按虚拟时钟推进车辆与无人机真实轨迹')
box(50,84,46,6,'无人机到达客户：\n查询隐藏环境（规划器不可见）',fc='#fff3e0',ec='#e65100')
box(88,84,20,6,'可空送：\n服务60 s后\n释放包裹',fs=9.5)
box(50,74,62,6,'失效揭示：包裹锁定地送并留在机上；合并同刻观察\n结算已完成动作 → 截断 → 生成公开快照 Σ(t_n)',fc='#fff3e0',ec='#e65100')
box(50,63.5,62,7,'恢复初解（以名义残段为基座）：\n① 残段原回收承诺  ② MILP 恢复子问题（方法B）\n③ 接机目录枚举（回收车×回收点×继续子集），按 S/X 资格',fc='#fce4ec',ec='#ad1457')
box(50,49.5,66,14.5,'恢复 ALNS（统一预算：60 s 或 1000 次评价）\n· 算子选择：分段轮盘权重 / Q-learning（方法A）\n· 6 种移除 × 2 种修复（代理分数）\n· 5 个几何起点 + 坐标细化（连续放飞位置）\n· 固定结构时序与充电 LP；局部事件重排（≤6 事件）\n· SA 接受；周期性重解 MILP 恢复子问题（方法B）',fc='#ede7f6',ec='#4527a0')
box(50,37,62,5,'独立核验（重放几何、时序、能量、货物流与成本）')
box(50,28,46,6,'找到核验可行后缀？',fc='#fff8e1',ec='#f9a825')
box(88,28,20,7,'STOPPED_NO_\nFEASIBLE_SUFFIX\n（保留真实前缀）',fs=9)
box(50,18,62,5,'执行新后缀；若再次揭示失效则从该策略自身真实状态重规划')
box(50,8,62,5,'班次结束：全部无人机随车入库 → 回合重放核验 → 输出成本与账本',fc='#e8f5e9',ec='#2e7d32')
arr(50,117.5,50,114.5); arr(50,108,50,104.5); arr(50,99.5,50,96.5); arr(50,90.5,50,87.5)
arr(73.5,84,77.5,84,'是'); ax.annotate('',xy=(81,93),xytext=(88,87.5),arrowprops=dict(arrowstyle='->',lw=1.0,color='#777',connectionstyle='angle,angleA=90,angleB=0'))
arr(50,81,50,77.5,'否（失效）'); arr(50,71,50,67.5); arr(50,60,50,57.5); arr(50,41.5,50,39.5); arr(50,34.5,50,31)
arr(73,28,77.5,28,'否',off=(0,1)); arr(50,25,50,20.5,'是'); arr(50,15.5,50,10.5)
ax.annotate('',xy=(19,93),xytext=(19,18),arrowprops=dict(arrowstyle='->',lw=1.0,color='#777',connectionstyle='arc3,rad=0'))
ax.plot([19,19],[18,18]); ax.text(10,55,'下一次\n到达事件',fontsize=9,color='#555')
plt.savefig('/workspace/thesis/paper/figures/fig4_1_framework.png',dpi=200,bbox_inches='tight')
print('saved', plt.rcParams['font.family'])
