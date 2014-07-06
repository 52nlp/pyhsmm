# distutils: extra_compile_args = -O3 -w -DEIGEN_DONT_PARALLELIZE -DNDEBUG -fopenmp -std=c++11
# distutils: extra_link_args = -fopenmp
# distutils: language = c++
# distutils: include_dirs = deps/Eigen3/ internals/

import numpy as np
cimport numpy as np

from libcpp.vector cimport vector
from libc.stdint cimport int32_t, int64_t
from cython cimport floating

from cython.parallel import prange

cdef extern from "temp.h":
    cdef cppclass dummy[Type]:
        dummy()
        void getstats(
            int M, int T, int D, int32_t *stateseq, Type *data,
            Type *stats) nogil
        void gmm_likes(
            int T, int Tblock, int N, int K, int D,
            Type *data, Type *weights,
            Type *Js, Type *mus_times_Js, Type *normalizers,
            int32_t *changepoints,
            Type *aBBl)

def getstats(num_states, stateseqs, datas):
    cdef int i
    cdef dummy[double] ref

    cdef int M = num_states
    cdef int K = len(datas)
    cdef int D = datas[0].shape[1]
    cdef int32_t[::1] Ts = np.array([d.shape[0] for d in datas]).astype('int32')

    cdef vector[int32_t*] stateseqs_v
    cdef vector[double*] datas_v
    cdef double[:,:] temp
    cdef int32_t[:] temp2
    for i in range(K):
        temp = datas[i]
        datas_v.push_back(&temp[0,0])
        temp2 = stateseqs[i]
        stateseqs_v.push_back(&temp2[0])

    cdef double[:,:,::1] out = np.zeros((2*K,M,2*D+1)) # NOTE: 2*K to avoid false sharing

    with nogil:
        for i in prange(K):
            ref.getstats(M,Ts[i],D,stateseqs_v[i],datas_v[i],&out[2*i,0,0])

    ret = []
    for row in np.sum(out,axis=0):
        n = row[-1]
        xbar = row[:D] / (n if n > 0 else 1.)
        sumsq = row[D:2*D] - 2*xbar*row[:D] + n*xbar**2
        ret.append((n,xbar,sumsq))
    return ret

# NOTE: this one isn't parallelized because it should be called once per data
# sequence and there is joblib parallelism happening over data sequences. We
# could openmp it with fewer threads...
def gmm_likes(
        floating[:,::1] data not None,        # T x D
        floating[:,:,::1] sigmas not None,    # N x K x D
        floating[:,:,::1] mus not None,       # N x K x D
        floating[:,::1] weights not None,     # N x K
        int32_t[:,::1] changepoints not None, # T x 2
        floating[:,::1] aBBl not None,        # T x N
        ):
    cdef dummy[floating] ref
    cdef int T = data.shape[0]
    cdef int Tblock = aBBl.shape[0]
    cdef int N = sigmas.shape[0]
    cdef int K = sigmas.shape[1]
    cdef int D = sigmas.shape[2]

    cdef floating[:,:,::1] Js = -1./(2*np.asarray(sigmas))
    cdef floating[:,:,::1] mus_times_Js = 2*np.asarray(mus)*np.asarray(Js)
    cdef floating[:,::1] normalizers = \
            (np.asarray(mus)**2*np.asarray(Js) \
            - 1./2*np.log(2*np.pi*np.asarray(sigmas))).sum(2)

    ref.gmm_likes(T,Tblock,N,K,D,
        &data[0,0],&weights[0,0],
        &Js[0,0,0],&mus_times_Js[0,0,0],&normalizers[0,0],
        &changepoints[0,0],
        &aBBl[0,0])
    return aBBl

