# distutils: name = internals.test2
# distutils: sources = internals/cpp_eigen_code/mult_fast.cpp
# distutils: language = c++
# distutils: extra_compile_args = -O3 -w -march=native
# distutils: include_dirs = deps/Eigen3/

# TODO -DEIGEN_DONT_PARALLELIZE sometimes
# TODO should resample in the same code? temp arrays for messages are the heavy
# things, and each message passing step is going to take a while. but we don't
# want to call malloc for the whole enchilada every time. the python code should
# probably handle temporaries and keep them around across iterations. it can
# just allocate Nparallel ones each of size max(Ts)

import numpy as np
cimport numpy as np

import cython
from libc.stdint cimport int32_t
from libcpp.vector cimport vector


cdef extern from "mult_fast.h" namespace "std":
    void c_fast_mult "fast_mult" (
        int N, int32_t *Nsubs, int32_t *rs, float *ps,
        float *super_trans, vector[float*]& sub_transs, vector[float*]& sub_inits,
        float *v, float *out)

    float c_messages_backwards_normalized "messages_backwards_normalized" (
        int T, int bigN, int N, int32_t *Nsubs,
        int32_t *rs, float *ps, float *super_trans,
        vector[float*]& sub_transs, vector[float*]& sub_inits, vector[float*]& aBls,
        float *betan)


@cython.boundscheck(False)
@cython.wraparound(False)
def fast_mult(
        np.ndarray[np.float32_t,ndim=1,mode='c'] v not None,
        np.ndarray[np.float32_t,ndim=2,mode='c'] super_trans not None,
        np.ndarray[np.int32_t,ndim=1,mode='c'] rs not None,
        np.ndarray[np.float32_t,ndim=1,mode='c'] ps not None,
        list sub_transs,
        list sub_initstates):

    # create Nsubs array
    cdef np.ndarray[np.int32_t,ndim=1,mode='c'] Nsubs
    Nsubs = np.ascontiguousarray([s.shape[0] for s in sub_transs],dtype='int32')

    # pack sub_transs (list of numpy arrays) into a std::vector<float *>
    cdef vector[float*] sub_transs_vect
    cdef np.ndarray[np.float32_t,ndim=2,mode='c'] temp
    for i in xrange(len(sub_transs)):
        temp = sub_transs[i]
        sub_transs_vect.push_back(&temp[0,0])

    # pack sub_initstates (list of numpy arrays) into a std::vector
    cdef vector[float*] sub_initstates_vect
    cdef np.ndarray[np.float32_t,ndim=1,mode='c'] temp2
    for i in xrange(len(sub_initstates)):
        temp2 = sub_initstates[i]
        sub_initstates_vect.push_back(&temp2[0])

    # allocate output
    cdef np.ndarray[np.float32_t,ndim=1,mode='c'] out = np.zeros(v.shape[0],dtype='float32')

    # call the routine
    c_fast_mult(super_trans.shape[0],&Nsubs[0],&rs[0],&ps[0],&super_trans[0,0],
            sub_transs_vect,sub_initstates_vect,&v[0],&out[0])

    return out

@cython.boundscheck(False)
@cython.wraparound(False)
def messages_backwards_normalized(
        np.ndarray[np.float32_t,ndim=2,mode='c'] super_trans not None,
        np.ndarray[np.int32_t,ndim=1,mode='c'] rs not None,
        np.ndarray[np.float32_t,ndim=1,mode='c'] ps not None,
        list sub_transs,
        list sub_initstates,
        list aBls,
        np.ndarray[np.float32_t,ndim=2,mode='c'] betan = None):

    # create Nsubs array
    cdef np.ndarray[np.int32_t,ndim=1,mode='c'] Nsubs
    Nsubs = np.ascontiguousarray([s.shape[0] for s in sub_transs],dtype='int32')

    # pack sub_transs (list of numpy arrays) into a std::vector<float *>
    cdef vector[float*] sub_transs_vect
    cdef np.ndarray[np.float32_t,ndim=2,mode='c'] temp
    for i in xrange(len(sub_transs)):
        temp = sub_transs[i]
        sub_transs_vect.push_back(&temp[0,0])

    # pack sub_initstates (list of numpy arrays) into a std::vector<float *>
    cdef vector[float*] sub_initstates_vect
    cdef np.ndarray[np.float32_t,ndim=1,mode='c'] temp2
    for i in xrange(len(sub_initstates)):
        temp2 = sub_initstates[i]
        sub_initstates_vect.push_back(&temp2[0])

    # pack aBls (list of numpy arrays) into a std::vector<float *>
    cdef vector[float*] aBls_vect
    cdef np.ndarray[np.float32_t,ndim=2,mode='c'] temp3
    for i in xrange(len(sub_initstates)):
        temp3 = aBls[i]
        aBls_vect.push_back(&temp3[0,0])

    # allocate output
    cdef int T = aBls[0].shape[0]
    cdef int bigN = sum([r*Nsub for r,Nsub in zip(rs,Nsubs)])
    if betan is None:
        betan = np.empty((T,bigN),dtype='float32')

    # call the routine
    loglike = c_messages_backwards_normalized(
            T,bigN,super_trans.shape[0],&Nsubs[0],
            &rs[0],&ps[0],&super_trans[0,0],
            sub_transs_vect,sub_initstates_vect,aBls_vect,
            &betan[0,0])

    return betan, loglike

