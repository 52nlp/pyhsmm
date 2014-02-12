from __future__ import division
import numpy as np
import itertools, collections, operator, random, abc, copy
from matplotlib import pyplot as plt
from matplotlib import cm

from basic.abstractions import Model, ModelGibbsSampling, \
        ModelEM, ModelMAPEM, ModelMeanField, ModelMeanFieldSVI
import basic.distributions
from internals import states, initial_state, transitions
import util.general
from util.profiling import line_profiled

# TODO get rid of logical indexing with a data abstraction

################
#  HMM Mixins  #
################

class _HMMBase(Model):
    _states_class = states.HMMStatesPython
    _trans_class = transitions.HMMTransitions
    _trans_conc_class = transitions.HMMTransitionsConc
    _init_state_class = initial_state.HMMInitialState

    def __init__(self,
            obs_distns,
            trans_distn=None,
            alpha=None,alpha_a_0=None,alpha_b_0=None,trans_matrix=None,
            init_state_distn=None,init_state_concentration=None,pi_0=None):
        self.obs_distns = obs_distns
        self.states_list = []

        if trans_distn is not None:
            self.trans_distn = trans_distn
        elif not None in (alpha_a_0,alpha_b_0):
            self.trans_distn = self._trans_conc_class(
                    num_states=len(obs_distns),
                    alpha_a_0=alpha_a_0,alpha_b_0=alpha_b_0,
                    trans_matrix=trans_matrix)
        else:
            self.trans_distn = self._trans_class(
                    num_states=len(obs_distns),alpha=alpha,trans_matrix=trans_matrix)

        if init_state_distn is not None:
            self.init_state_distn = init_state_distn
        else:
            self.init_state_distn = self._init_state_class(
                    model=self,
                    init_state_concentration=init_state_concentration,
                    pi_0=pi_0)

        self._clear_caches()

    def add_data(self,data,stateseq=None,**kwargs):
        self.states_list.append(
                self._states_class(
                    model=self,data=data,
                    stateseq=stateseq,**kwargs))

    def generate(self,T,keep=True):
        s = self._states_class(model=self,T=T,initialize_from_prior=True)
        data, stateseq = s.generate_obs(), s.stateseq
        if keep:
            self.states_list.append(s)
        return data, stateseq

    def log_likelihood(self,data=None,**kwargs):
        if data is not None:
            self.add_data(data=data,generate=False,**kwargs)
            return self.states_list.pop().log_likelihood()
        else:
            return sum(s.log_likelihood() for s in self.states_list)

    @property
    def stateseqs(self):
        return [s.stateseq for s in self.states_list]

    @property
    def num_states(self):
        return len(self.obs_distns)

    @property
    def num_parameters(self):
        return sum(o.num_parameters() for o in self.obs_distns) + self.num_states**2

    ### predicting

    # TODO remove this section

    def _resample_from_mf(self):
        self.trans_distn._resample_from_mf()
        self.init_state_distn._resample_from_mf()
        for o in self.obs_distns:
            o._resample_from_mf()


    def mf_block_predictive_likelihoods(self,test_data,blocklens,nsamples=100,**kwargs):
        self.add_data(data=test_data,stateseq=np.zeros(test_data.shape[0]),**kwargs)
        s = self.states_list.pop()
        alphal = s.messages_forwards_log()

        outss = []
        for itr in range(nsamples):
            self._resample_from_mf()
            outs = []
            for k in blocklens:
                outs.append((np.logaddexp.reduce(alphal[k:],axis=1)
                        - np.logaddexp.reduce(alphal[:-k],axis=1)).mean())
            outss.append(np.asarray(outs))

        # return outss
        return reduce(operator.add,outss,0)/nsamples

    ### caching

    def _clear_caches(self):
        for s in self.states_list:
            s.clear_caches()

    def __getstate__(self):
        self._clear_caches()
        return self.__dict__.copy()

    ### plotting

    def _get_used_states(self,states_objs=None):
        if states_objs is None:
            states_objs = self.states_list
        canonical_ids = collections.defaultdict(itertools.count().next)
        for s in states_objs:
            for state in s.stateseq:
                canonical_ids[state]
        return map(operator.itemgetter(0),
                sorted(canonical_ids.items(),key=operator.itemgetter(1)))

    def _get_colors(self,states_objs=None):
        if states_objs is not None:
            states = self._get_used_states(states_objs)
        else:
            states = range(len(self.obs_distns))
        numstates = len(states)
        return dict(zip(states,np.linspace(0,1,numstates,endpoint=True)))

    def plot_observations(self,colors=None,states_objs=None):
        if states_objs is None:
            states_objs = self.states_list

        cmap = cm.get_cmap()

        if len(states_objs) > 0:
            if colors is None:
                colors = self._get_colors(states_objs)
            used_states = self._get_used_states(states_objs)
            for state,o in enumerate(self.obs_distns):
                if state in used_states:
                    o.plot(
                        color=cmap(colors[state]),
                        data=[s.data[s.stateseq == state] if s.data is not None else None
                            for s in states_objs],
                        indices=[np.where(s.stateseq == state)[0] for s in states_objs],
                        label='%d' % state)
        else:
            N = len(self.obs_distns)
            colors = self._get_colors()
            weights = np.repeat(1./N,N).dot(
                    np.linalg.matrix_power(self.trans_distn.trans_matrix,1000))
            for state, o in enumerate(self.obs_distns):
                o.plot(
                        color=cmap(colors[state]),
                        label='%d' % state,
                        alpha=min(1.,weights[state]+0.05))
        plt.title('Observation Distributions')

    def plot(self,color=None,legend=False):
        plt.gcf() #.set_size_inches((10,10))

        if len(self.states_list) > 0:
            colors = self._get_colors()
            num_subfig_cols = len(self.states_list)
            for subfig_idx,s in enumerate(self.states_list):
                plt.subplot(2,num_subfig_cols,1+subfig_idx)
                self.plot_observations(colors=colors,states_objs=[s])

                plt.subplot(2,num_subfig_cols,1+num_subfig_cols+subfig_idx)
                s.plot(colors_dict=colors)

            if legend:
                plt.legend()
        else:
            self.plot_observations()

class _HMMGibbsSampling(_HMMBase,ModelGibbsSampling):
    def resample_model(self):
        self.resample_parameters()
        self.resample_states()

    def resample_parameters(self):
        self.resample_obs_distns()
        self.resample_trans_distn()
        self.resample_init_state_distn()

    def resample_obs_distns(self):
        for state, distn in enumerate(self.obs_distns):
            distn.resample([s.data[s.stateseq == state] for s in self.states_list])
        self._clear_caches()

    def resample_trans_distn(self):
        self.trans_distn.resample([s.stateseq for s in self.states_list])
        self._clear_caches()

    def resample_init_state_distn(self):
        self.init_state_distn.resample([s.stateseq[0] for s in self.states_list])
        self._clear_caches()

    def resample_states(self):
        for s in self.states_list:
            s.resample()

    def copy_sample(self):
        new = copy.copy(self)
        new.obs_distns = [o.copy_sample() for o in self.obs_distns]
        new.trans_distn = self.trans_distn.copy_sample()
        new.init_state_distn = self.init_state_distn.copy_sample()
        new.states_list = [s.copy_sample(new) for s in self.states_list]
        return new

    ### parallel

    def add_data_parallel(self,data,broadcast=False,**kwargs):
        import parallel
        self.add_data(data=data,**kwargs)
        if broadcast:
            parallel.broadcast_data(self._get_parallel_data(data))
        else:
            parallel.add_data(self._get_parallel_data(self.states_list[-1]))

    def resample_model_parallel(self,temp=None):
        self.resample_parameters(temp=temp)
        self.resample_states_parallel(temp=temp)

    def resample_states_parallel(self,temp=None):
        import parallel
        states_to_resample = self.states_list
        self.states_list = [] # removed because we push the global model
        raw = parallel.map_on_each(
                self._state_sampler,
                [self._get_parallel_data(s) for s in states_to_resample],
                kwargss=self._get_parallel_kwargss(states_to_resample),
                engine_globals=dict(global_model=self,temp=temp))
        for s, stateseq in zip(states_to_resample,raw):
            s.stateseq = stateseq
        self.states_list = states_to_resample

    def _get_parallel_data(self,states_obj):
        return states_obj.data

    def _get_parallel_kwargss(self,states_objs):
        # this method is broken out so that it can be overridden
        return None

    @staticmethod
    @util.general.engine_global_namespace # access to engine globals
    def _state_sampler(data,**kwargs):
        # expects globals: global_model, temp
        global_model.add_data(data=data,initialize_from_prior=False,temp=temp,**kwargs)
        return global_model.states_list.pop().stateseq

class _HMMMeanField(_HMMBase,ModelMeanField):
    def meanfield_coordinate_descent_step(self):
        self._meanfield_update_sweep()
        return self._vlb()

    def _meanfield_update_sweep(self):
        for s in self.states_list:
            if not hasattr(s,'mf_expectations'):
                s.meanfieldupdate()

        for state, o in enumerate(self.obs_distns):
            o.meanfieldupdate([s.data for s in self.states_list],
                    [s.mf_expectations[:,state] for s in self.states_list])
        self.trans_distn.meanfieldupdate(
                [s.mf_expected_transcounts for s in self.states_list])
        self.init_state_distn.meanfieldupdate(None,
                [s.mf_expectations[0] for s in self.states_list])
        for s in self.states_list:
            s.meanfieldupdate()

    def _vlb(self):
        vlb = 0.
        vlb += sum(s.get_vlb() for s in self.states_list)
        vlb += self.trans_distn.get_vlb()
        vlb += self.init_state_distn.get_vlb()
        vlb += sum(o.get_vlb() for o in self.obs_distns)
        return vlb

class _HMMSVI(_HMMBase,ModelMeanFieldSVI):
    def meanfield_sgdstep(self,minibatch,minibatchfrac,stepsize):
        minibatch = minibatch if isinstance(minibatch,list) else [minibatch]
        mb_states_list = []
        for mb in minibatch:
            self.add_data(mb,stateseq=np.zeros(mb.shape[0])) # dummy
            mb_states_list.append(self.states_list.pop())

        for s in mb_states_list:
            s.meanfieldupdate()

        for state, o in enumerate(self.obs_distns):
            o.meanfield_sgdstep(
                    [s.data for s in mb_states_list],
                    [s.mf_expectations[:,state] for s in mb_states_list],
                    minibatchfrac,stepsize)
        self.trans_distn.meanfield_sgdstep(
                [s.mf_expected_transcounts for s in mb_states_list],
                minibatchfrac,stepsize)
        self.init_state_distn.meanfield_sgdstep(
                None,[s.mf_expectations[0] for s in mb_states_list],
                minibatchfrac,stepsize)

    def _meanfield_sgdstep_batch(self,stepsize):
        # NOTE: this method is for convenient testing; it holds onto the data
        # and computes an SGD step with respect to all of it, then reports the
        # variational lower bound on all of it
        for s in self.states_list:
            if not hasattr(s,'mf_expectations'):
                s.meanfieldupdate()

        self.meanfield_sgdstep([s.data for s in self.states_list],1.,stepsize)

        # NOTE: wasteful to recompute these, but we must do them after the
        # updates have been computed for the vlb to be valid
        for s in self.states_list:
            s.meanfieldupdate()
        return self._vlb()

class _HMMEM(_HMMBase,ModelEM):
    def EM_step(self):
        assert len(self.states_list) > 0, 'Must have data to run EM'
        self._clear_caches()
        self._E_step()
        self._M_step()

    def _E_step(self):
        for s in self.states_list:
            s.E_step()

    def _M_step(self):
        for state, distn in enumerate(self.obs_distns):
            distn.max_likelihood([s.data for s in self.states_list],
                    [s.expectations[:,state] for s in self.states_list])

        self.init_state_distn.max_likelihood(
                None,weights=[s.expectations[0] for s in self.states_list])

        self.trans_distn.max_likelihood(
                expected_transcounts=[s.expected_transcounts for s in self.states_list])

    def BIC(self,data=None):
        '''
        BIC on the passed data. If passed data is None (default), calculates BIC
        on the model's assigned data
        '''
        # NOTE: in principle this method computes the BIC only after finding the
        # maximum likelihood parameters (or, of course, an EM fixed-point as an
        # approximation!)
        assert data is None and len(self.states_list) > 0, 'Must have data to get BIC'
        if data is None:
            return -2*sum(self.log_likelihood(s.data).sum() for s in self.states_list) + \
                        self.num_parameters() * np.log(
                                sum(s.data.shape[0] for s in self.states_list))
        else:
            return -2*self.log_likelihood(data) + self.num_parameters() * np.log(data.shape[0])

class _HMMViterbiEM(_HMMBase,ModelMAPEM):
    def Viterbi_EM_fit(self, tol=0.1, maxiter=20):
        return self.MAP_EM_fit(tol, maxiter)

    def Viterbi_EM_step(self):
        assert len(self.states_list) > 0, 'Must have data to run Viterbi EM'
        self._clear_caches()

        ## Viterbi step
        for s in self.states_list:
            s.Viterbi()

        ## M step
        for state, distn in enumerate(self.obs_distns):
            distn.max_likelihood([s.data[s.stateseq == state] for s in self.states_list])

        self.init_state_distn.max_likelihood(
                np.array([s.stateseq[0] for s in self.states_list]))

        self.trans_distn.max_likelihood([s.stateseq for s in self.states_list])

    MAP_EM_step = Viterbi_EM_step

class _WeakLimitHDPMixin(object):
    def __init__(self,
            obs_distns,
            trans_distn=None,alpha=None,alpha_a_0=None,alpha_b_0=None,
            gamma=None,gamma_a_0=None,gamma_b_0=None,trans_matrix=None,
            **kwargs):

        if trans_distn is not None:
            trans_distn = trans_distn
        elif not None in (alpha_a_0,alpha_b_0):
            trans_distn = self._trans_conc_class(
                    num_states=len(obs_distns),
                    alpha_a_0=alpha_a_0,alpha_b_0=alpha_b_0,
                    gamma_a_0=gamma_a_0,gamma_b_0=gamma_b_0,
                    trans_matrix=trans_matrix)
        else:
            trans_distn = self._trans_class(
                    num_states=len(obs_distns),alpha=alpha,gamma=gamma,
                    trans_matrix=trans_matrix)

        super(_WeakLimitHDPMixin,self).__init__(
                obs_distns=obs_distns,trans_distn=trans_distn,**kwargs)

################
#  HMM models  #
################

class HMMPython(_HMMGibbsSampling,_HMMSVI,_HMMMeanField,_HMMEM,_HMMViterbiEM):
    pass

class HMM(HMMPython):
    _states_class = states.HMMStatesEigen

class WeakLimitHDPHMMPython(_WeakLimitHDPMixin,HMMPython):
    # NOTE: shouldn't really inherit EM or ViterbiEM, but it's convenient!
    _trans_class = transitions.WeakLimitHDPHMMTransitions
    _trans_conc_class = transitions.WeakLimitHDPHMMTransitionsConc

class WeakLimitHDPHMM(_WeakLimitHDPMixin,HMM):
    _trans_class = transitions.WeakLimitHDPHMMTransitions
    _trans_conc_class = transitions.WeakLimitHDPHMMTransitionsConc

class DATruncHDPHMM(_WeakLimitHDPMixin,HMMPython):
    # NOTE: weak limit mixin is poorly named; we just want its init method
    _trans_class = transitions.DATruncHDPHMMTransitions
    _trans_conc_class = None

class DATruncHDPHMM(_WeakLimitHDPMixin,HMM):
    _trans_class = transitions.DATruncHDPHMMTransitions
    _trans_conc_class = None

class WeakLimitStickyHDPHMM(WeakLimitHDPHMM):
    # TODO concentration resampling, too!
    def __init__(self,obs_distns,
            kappa=None,alpha=None,gamma=None,trans_matrix=None,**kwargs):
        trans_distn = transitions.WeakLimitStickyHDPHMMTransitions(
                num_states=len(obs_distns),
                kappa=kappa,alpha=alpha,gamma=gamma,trans_matrix=trans_matrix)
        super(WeakLimitStickyHDPHMM,self).__init__(
                obs_distns=obs_distns,trans_distn=trans_distn,**kwargs)

#################
#  HSMM Mixins  #
#################

class _HSMMBase(_HMMBase):
    _states_class = states.HSMMStatesPython
    _trans_class = transitions.HSMMTransitions
    _trans_class_conc_class = transitions.HSMMTransitionsConc
    # _init_steady_state_class = initial_state.HSMMSteadyState # TODO

    def __init__(self,dur_distns,**kwargs):
        self.dur_distns = dur_distns
        super(_HSMMBase,self).__init__(**kwargs)

    def add_data(self,data,stateseq=None,trunc=None,
            right_censoring=True,left_censoring=False,**kwargs):
        self.states_list.append(self._states_class(
            model=self,
            data=np.asarray(data),
            stateseq=stateseq,
            right_censoring=right_censoring,
            left_censoring=left_censoring,
            trunc=trunc,
            **kwargs))

    @property
    def stateseqs_norep(self):
        return [s.stateseq_norep for s in self.states_list]

    @property
    def durations(self):
        return [s.durations for s in self.states_list]

    @property
    def num_parameters(self):
        return sum(o.num_parameters() for o in self.obs_distns) \
                + sum(d.num_parameters() for d in self.dur_distns) \
                + self.num_states**2 - self.num_states

    def plot_durations(self,colors=None,states_objs=None):
        if colors is None:
            colors = self._get_colors()
        if states_objs is None:
            states_objs = self.states_list

        cmap = cm.get_cmap()
        used_states = self._get_used_states(states_objs)
        for state,d in enumerate(self.dur_distns):
            if state in used_states:
                d.plot(color=cmap(colors[state]),
                        data=[s.durations[s.stateseq_norep == state]
                            for s in states_objs])
        plt.title('Durations')

    def plot(self,color=None):
        plt.gcf() #.set_size_inches((10,10))
        colors = self._get_colors()

        num_subfig_cols = len(self.states_list)
        for subfig_idx,s in enumerate(self.states_list):
            plt.subplot(3,num_subfig_cols,1+subfig_idx)
            self.plot_observations(colors=colors,states_objs=[s])

            plt.subplot(3,num_subfig_cols,1+num_subfig_cols+subfig_idx)
            s.plot(colors_dict=colors)

            plt.subplot(3,num_subfig_cols,1+2*num_subfig_cols+subfig_idx)
            self.plot_durations(colors=colors,states_objs=[s])

class _HSMMGibbsSampling(_HSMMBase,_HMMGibbsSampling):
    def resample_parameters(self):
        self.resample_dur_distns()
        super(_HSMMGibbsSampling,self).resample_parameters()

    @line_profiled
    def resample_dur_distns(self):
        for state, distn in enumerate(self.dur_distns):
            distn.resample_with_truncations(
            data=
            [s.durations_censored[s.untrunc_slice][s.stateseq_norep[s.untrunc_slice] == state]
                for s in self.states_list],
            truncated_data=
            [s.durations_censored[s.trunc_slice][s.stateseq_norep[s.trunc_slice] == state]
                for s in self.states_list])
        self._clear_caches()

    def copy_sample(self):
        new = super(_HSMMGibbsSampling,self).copy_sample()
        new.dur_distns = [d.copy_sample() for d in self.dur_distns]
        return new

    ### parallel

    def _get_parallel_kwargss(self,states_objs):
        return [dict(trunc=s.trunc,left_censoring=s.left_censoring,
                    right_censoring=s.right_censoring) for s in states_objs]

class _HSMMEM(_HSMMBase,_HMMEM):
    def _M_step(self):
        super(_HSMMEM,self)._M_step()
        for state, distn in enumerate(self.dur_distns):
            distn.max_likelihood(
                    [np.arange(1,s.T+1) for s in self.states_list],
                    [s.expected_durations[state] for s in self.states_list])

class _HSMMMeanField(_HSMMBase,_HMMMeanField):
    def _meanfield_update_sweep(self):
        # NOTE: need to do states last (in super)
        for s in self.states_list:
            if not hasattr(s,'mf_expectations'):
                s.meanfieldupdate()
        for state, d in enumerate(self.dur_distns):
            d.meanfieldupdate(
                    [np.arange(1,s.T+1) for s in self.states_list],
                    [s.mf_expected_durations[state] for s in self.states_list])
        super(_HSMMMeanField,self)._meanfield_update_sweep()

    def _vlb(self):
        vlb = super(_HSMMMeanField,self)._vlb()
        vlb += sum(d.get_vlb() for d in self.dur_distns)
        return vlb

class _HSMMSVI(_HSMMBase,_HMMSVI):
    def meanfield_sgdstep(self,minibatch,minibatchfrac,stepsize):
        super(_HSMMSVI,self).meanfield_sgdstep(minibatch,minibatchfrac,stepsize)
        for state, d in enumerate(self.dur_distns):
            d.meanfield_sgdstep(
                    [np.arange(1,s.T+1) for s in self.states_list],
                    [s.mf_expected_durations[state] for s in self.states_list],
                    minibatchfrac,stepsize)

class _HSMMINBEMMixin(_HMMEM,ModelEM):
    def EM_step(self):
        super(_HSMMINBEMMixin,self).EM_step()
        for state, distn in enumerate(self.dur_distns):
            distn.max_likelihood(data=None,stats=(
                sum(s.expected_dur_ns[state] for s in self.states_list),
                sum(s.expected_dur_tots[state] for s in self.states_list)))

class _HSMMViterbiEM(_HSMMBase,_HMMViterbiEM):
    def Viterbi_EM_step(self):
        super(_HSMMViterbiEM,self).Viterbi_EM_step()
        for state, distn in enumerate(self.dur_distns):
            distn.max_likelihood(
                    [s.durations[s.stateseq_norep == state] for s in self.states_list])

class _HSMMPossibleChangepointsMixin(object):
    _states_class = states.HSMMStatesPossibleChangepoints

    def add_data(self,data,changepoints,**kwargs):
        super(_HSMMPossibleChangepointsMixin,self).add_data(
                data=data,changepoints=changepoints,**kwargs)

    def _get_parallel_kwargss(self,states_objs):
        # TODO this is wasteful: it should be in _get_parallel_data
        dcts = super(HSMMPossibleChangepoints,self)._get_parallel_kwargss(states_objs)
        for dct, states_obj in zip(dcts,states_objs):
            dct.update(dict(changepoints=states_obj.changepoints))
        return dcts

#################
#  HSMM Models  #
#################

class HSMMPython(_HSMMGibbsSampling,_HSMMSVI,_HSMMMeanField,_HSMMViterbiEM,_HSMMEM):
    _trans_class = transitions.HSMMTransitions
    _trans_conc_class = transitions.HSMMTransitionsConc

class HSMM(HSMMPython):
    _states_class = states.HSMMStatesEigen

class HSMMHMMEmbedding(HSMMPython):
    _states_class = states.HSMMStatesEmbedding

class WeakLimitHDPHSMMPython(_WeakLimitHDPMixin,HSMMPython):
    # NOTE: shouldn't technically inherit EM or ViterbiEM, but it's convenient
    _trans_class = transitions.WeakLimitHDPHSMMTransitions
    _trans_conc_class = transitions.WeakLimitHDPHSMMTransitionsConc

class WeakLimitHDPHSMM(_WeakLimitHDPMixin,HSMM):
    _trans_class = transitions.WeakLimitHDPHSMMTransitions
    _trans_conc_class = transitions.WeakLimitHDPHSMMTransitionsConc

class DATruncHDPHSMM(_WeakLimitHDPMixin,HSMM):
    # NOTE: weak limit mixin is poorly named; we just want its init method
    _trans_class = transitions.DATruncHDPHSMMTransitions
    _trans_conc_class = None

class HSMMIntNegBin(_HSMMGibbsSampling,_HSMMSVI,_HSMMViterbiEM):
    _trans_class = transitions.HSMMTransitions
    _trans_conc_class = transitions.HSMMTransitionsConc
    _states_class = states.HSMMStatesIntegerNegativeBinomial

    def _resample_from_mf(self):
        super(HSMMIntNegBin,self)._resample_from_mf()
        for d in self.dur_distns:
            d._resample_from_mf()

    def _vlb(self):
        return 0. # TODO

class WeakLimitHDPHSMMIntNegBin(_WeakLimitHDPMixin,HSMMIntNegBin):
    _trans_class = transitions.WeakLimitHDPHSMMTransitions
    _trans_class_conc_class = transitions.WeakLimitHDPHSMMTransitionsConc

class HSMMIntNegBinVariant(_HSMMGibbsSampling,_HSMMINBEMMixin,_HSMMViterbiEM):
    _trans_class = transitions.HSMMTransitions
    _trans_conc_class = transitions.HSMMTransitionsConc
    _states_class = states.HSMMStatesIntegerNegativeBinomialVariant

class WeakLimitHDPHSMMIntNegBinVariant(_WeakLimitHDPMixin,HSMMIntNegBinVariant):
    _trans_class = transitions.WeakLimitHDPHSMMTransitions
    _trans_class_conc_class = transitions.WeakLimitHDPHSMMTransitionsConc


class HSMMPossibleChangepointsPython(_HSMMPossibleChangepointsMixin,HSMMPython):
    pass

class HSMMPossibleChangepoints(_HSMMPossibleChangepointsMixin,HSMM):
    pass

class WeakLimitHDPHSMMPossibleChangepointsPython(_HSMMPossibleChangepointsMixin,WeakLimitHDPHSMMPython):
    pass

class WeakLimitHDPHSMMPossibleChangepoints(_HSMMPossibleChangepointsMixin,WeakLimitHDPHSMM):
    pass

