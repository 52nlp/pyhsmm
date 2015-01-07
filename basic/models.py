# These classes make aliases of class members and properties so as to make
# pybasicbayes mixture models look more like pyhsmm models. When comparing
# H(S)MM model fits to pybasicbayes mixture model fits, it's easier to write one
# code path by using these models.

import pybasicbayes
from ..util.general import rle

class _Labels(pybasicbayes.internals.labels.Labels):
    @property
    def T(self):
        return self.N

    @property
    def stateseq(self):
        return self.z

    @stateseq.setter
    def stateseq(self,stateseq):
        self.z = stateseq

    @property
    def stateseqs_norep(self):
        return rle(self.z)[0]

    @property
    def durations(self):
        return rle(self.z)[1]

class _MixturePropertiesMixin(object):
    _labels_class = _Labels

    @property
    def states_list(self):
        return self.labels_list

    @property
    def stateseqs(self):
        return [s.stateseq for s in self.states_list]

    @property
    def stateseqs_norep(self):
        return [s.stateseq_norep for s in self.states_list]

    @property
    def durations(self):
        return [s.durations for s in self.states_list]

    @property
    def obs_distns(self):
        return self.components

    @obs_distns.setter
    def obs_distns(self,distns):
        self.components = distns

class Mixture(_MixturePropertiesMixin,pybasicbayes.models.Mixture):
    pass

class MixtureDistribution(_MixturePropertiesMixin,pybasicbayes.models.MixtureDistribution):
    pass

