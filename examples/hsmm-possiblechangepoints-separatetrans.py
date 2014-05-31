from __future__ import division
import numpy as np
np.seterr(divide='ignore')
from matplotlib import pyplot as plt

import pyhsmm
from pyhsmm.util.text import progprint_xrange, progprint
from pyhsmm.util.general import sgd_passes

# TODO generate data from a separatetrans model

#####################
#  data generation  #
#####################

N = 4
T = 1000
obs_dim = 2

obs_hypparams = {'mu_0':np.zeros(obs_dim),
                'sigma_0':np.eye(obs_dim),
                'kappa_0':0.2,
                'nu_0':obs_dim+2}

dur_hypparams = {'alpha_0':4*30,
                 'beta_0':4}

true_obs_distns = [pyhsmm.distributions.Gaussian(**obs_hypparams) for state in range(N)]
true_dur_distns = [pyhsmm.distributions.PoissonDuration(**dur_hypparams) for state in range(N)]

truemodel = pyhsmm.models.HSMM(alpha=6.,init_state_concentration=6.,
                               obs_distns=true_obs_distns,
                               dur_distns=true_dur_distns)

datas = [truemodel.generate(T)[0] for itr in range(3)]

plt.figure()
truemodel.plot()
plt.gcf().suptitle('True HSMM')


# !!! get the changepoints !!!
# NOTE: usually these would be estimated by some external process; here I'm
# totally cheating and just getting them from the truth
changepointss = []
for s in truemodel.states_list:
    temp = np.concatenate(((0,),s.durations.cumsum()))
    changepoints = zip(temp[:-1],temp[1:])
    changepoints[-1] = (changepoints[-1][0],T) # because last duration might be censored
    changepointss.append(changepoints)

#########################
#  posterior inference  #
#########################

Nmax = 20

obs_distns = [pyhsmm.distributions.Gaussian(**obs_hypparams) for state in xrange(Nmax)]
dur_distns = [pyhsmm.distributions.PoissonDuration(**dur_hypparams) for state in xrange(Nmax)]

# posteriormodel = pyhsmm.models.WeakLimitHDPHSMMPossibleChangepointsSeparateTrans(
#         alpha=4.,gamma=4.,init_state_concentration=4.,
#         obs_distns=obs_distns,dur_distns=dur_distns)

posteriormodel = pyhsmm.models.HSMMPossibleChangepointsSeparateTrans(
        alpha=4.,init_state_concentration=4.,
        obs_distns=obs_distns,dur_distns=dur_distns)

### sampling

# for idx, (data, changepoints) in enumerate(zip(datas,changepointss)):
#     posteriormodel.add_data(data=data,changepoints=changepoints,group_id=idx)

# for idx in progprint_xrange(100):
#     posteriormodel.resample_model()

# plt.figure()
# posteriormodel.plot()

### mean field

for idx, (data, changepoints) in enumerate(zip(datas,changepointss)):
    # posteriormodel.add_data(data=data,changepoints=changepoints,group_id=0)
    posteriormodel.add_data(data=data,changepoints=changepoints,group_id=idx)

scores = []
for idx in progprint_xrange(50):
    scores.append(posteriormodel.meanfield_coordinate_descent_step())

plt.figure()
plt.plot(scores)

plt.figure()
posteriormodel.plot()

### SVI

# sgdseq = sgd_passes(
#         tau=0,kappa=0.7,npasses=20,
#         datalist=zip(range(len(datas)),datas,changepointss))

# for (group_id,data,changepoints), rho_t in progprint(sgdseq):
#     posteriormodel.meanfield_sgdstep(
#             data,changepoints=changepoints,group_id=group_id,
#             minibatchfrac=1./3,stepsize=rho_t)

# plt.figure()
# for idx, (data, changepoints) in enumerate(zip(datas,changepointss)):
#     posteriormodel.add_data(data,changepoints=changepoints,group_id=idx)
#     posteriormodel.states_list[-1].mf_Viterbi()
# posteriormodel.plot()

plt.show()

