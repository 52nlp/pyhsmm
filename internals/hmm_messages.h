#ifndef HMM_MESSAGES_H
#define HMM_MESSAGES_H

#include <Eigen/Core>
#include <stdint.h> // int32_t
#include <limits> // infinity

#include "nptypes.h"
#include "util.h"

// NOTE: HMM_TEMPS_ON_STACK is mainly for the OpenMP case, where dynamic
// allocation has locks and even then may lead to false sharing.
// It may be a dumb idea though, I haven't profiled it.

// NOTE: HMM_NOT_ROBUST switch needs to be benchmarked, removed if it doesn't
// make a difference

namespace hmm
{
    using namespace Eigen;
    using namespace std;
    using namespace nptypes;

    // Messages

    template <typename Type>
    void messages_backwards_log(int M, int T, Type *A, Type *aBl,
            Type *betal)
    {
        NPMatrix<Type> eA(A,M,M);
        NPMatrix<Type> eaBl(aBl,T,M);

        NPMatrix<Type> ebetal(betal,T,M);

#ifndef HMM_TEMPS_ON_STACK
        Matrix<Type,Dynamic,1> thesum(M);
#else
        Type thesum_buf[M] __attribute__((aligned(16)));
        NPVector<Type> thesum(thesum_buf,M);
#endif
        Type cmax;

        ebetal.row(T-1).setZero();
        for (int t=T-2; t>=0; t--) {
            thesum = (eaBl.row(t+1) + ebetal.row(t+1)).transpose();
            cmax = thesum.maxCoeff();
            ebetal.row(t) = (eA * (thesum.array() - cmax).exp().matrix()).array().log() + cmax;
        }
    }

    template <typename Type>
    void messages_forwards_log(int M, int T, Type *A, Type *pi0, Type *aBl,
            Type *alphal)
    {
        NPMatrix<Type> eA(A,M,M);
        NPArray<Type> epi0(pi0,1,M);
        NPArray<Type> eaBl(aBl,T,M);

        NPArray<Type> ealphal(alphal,T,M);

        Type cmax;

        ealphal.row(0) = epi0.log() + eaBl.row(0);
        for (int t=0; t<T-1; t++) {
            cmax = ealphal.row(t).maxCoeff();
#ifndef HMM_NOT_ROBUST
            if (likely(util::is_finite(cmax))) {
#endif
                ealphal.row(t+1) = ((ealphal.row(t) - cmax).exp().matrix() * eA).array().log()
                    + cmax + eaBl.row(t+1);
#ifndef HMM_NOT_ROBUST
            } else {
                ealphal.block(t+1,0,T-(t+1),M).setConstant(-numeric_limits<Type>::infinity());
                return;
            }
#endif
        }
    }

    template <typename Type>
    Type messages_forwards_normalized(int M, int T, Type *A, Type *pi0, Type *aBl,
            Type *alphan)
    {
        NPMatrix<Type> eA(A,M,M);
        NPArray<Type> eaBl(aBl,T,M);

        NPMatrix<Type> ealphan(alphan,T,M);

        Type logtot = 0.;
        Type cmax, norm;

#ifndef HMM_TEMPS_ON_STACK
        Matrix<Type,1,Dynamic> ein_potential(1,M);
#else
        Type in_potential_buf[M] __attribute__((aligned(16)));
        NPRowVector<Type> ein_potential(in_potential_buf,M);
#endif

        ein_potential = NPMatrix<Type>(pi0,1,M);
        for (int t=0; t<T; t++) {
            cmax = eaBl.row(t).maxCoeff();
            ealphan.row(t) = ein_potential.array() * (eaBl.row(t) - cmax).exp();
            norm = ealphan.row(t).sum();
#ifndef HMM_NOT_ROBUST
            if (likely(norm != 0)) {
#endif
                ealphan.row(t) /= norm;
                logtot += log(norm) + cmax;
#ifndef HMM_NOT_ROBUST
            } else {
                ealphan.block(t,0,T-1,M).setZero();
                return -numeric_limits<Type>::infinity();
            }
#endif
            ein_potential = ealphan.row(t) * eA;
        }
        return logtot;
    }

    // Sampling

    template <typename FloatType, typename IntType>
    void sample_forwards_log(
            int M, int T, FloatType *A, FloatType *pi0, FloatType *aBl, FloatType *betal,
            IntType *stateseq)
    {
        NPMatrix<FloatType> eA(A,M,M);
        NPMatrix<FloatType> eaBl(aBl,T,M);
        NPMatrix<FloatType> ebetal(betal,T,M);

#ifndef HMM_TEMPS_ON_STACK
        Array<FloatType,1,Dynamic> logdomain(M);
        Array<FloatType,1,Dynamic> nextstate_distr(M);
#else
        FloatType logdomain_buf[M] __attribute__((aligned(16)));
        NPRowVectorArray<FloatType> logdomain(logdomain_buf,M);
        FloatType nextstate_distr_buf[M] __attribute__((aligned(16)));
        NPRowVectorArray<FloatType> nextstate_distr(nextstate_distr_buf,M);
#endif

        nextstate_distr = NPVector<FloatType>(pi0,M);
        for (int t=0; t < T; t++) {
            logdomain = ebetal.row(t) + eaBl.row(t);
            nextstate_distr *= (logdomain - logdomain.maxCoeff()).exp();
            stateseq[t] = util::sample_discrete(M,nextstate_distr.data());
            nextstate_distr = eA.row(stateseq[t]);
        }
    }

    template <typename FloatType, typename IntType>
    void sample_backwards_normalized(int M, int T, FloatType *AT, FloatType *alphan,
            IntType *stateseq)
    {
        NPArray<FloatType> eAT(AT,M,M);
        NPArray<FloatType> ealphan(alphan,T,M);

#ifndef HMM_TEMPS_ON_STACK
        Array<FloatType,1,Dynamic> etemp(M);
#else
        FloatType temp_buf[M] __attribute__((aligned(16)));
        NPRowVectorArray<FloatType> etemp(temp_buf,M);
#endif

        stateseq[T-1] = util::sample_discrete(M,ealphan.row(T-1).data());
        for (int t=T-2; t>=0; t--) {
            etemp = eAT.row(stateseq[t+1]) * ealphan.row(t);
            stateseq[t] = util::sample_discrete(M,etemp.data());
        }
    }

    // Viterbi

    // TODO use nptypes
    template <typename FloatType, typename IntType>
    void viterbi(int M, int T, FloatType *A, FloatType *pi0, FloatType *aBl,
            IntType *stateseq)
    {
        // inputs
        Map<Matrix<FloatType,Dynamic,Dynamic>,Aligned> eA(A,M,M);
        Map<Matrix<FloatType,Dynamic,Dynamic>,Aligned> eaBl(aBl,M,T);
        Map<Array<FloatType,Dynamic,1>,Aligned> epi0(pi0,M);

        // locals
        MatrixXi args(M,T);
        Matrix<FloatType,Dynamic,Dynamic> eAl(M,M);
        eAl = eA.array().log();
        Matrix<FloatType,Dynamic,1> scores(M);
        Matrix<FloatType,Dynamic,1> prevscores(M);
        Matrix<FloatType,Dynamic,1> tempvec(M);
        int maxIndex;

        // computation!
        scores.setZero();
        for (int t=T-2; t>=0; t--) {
            for (int i=0; i<M; i++) {
                tempvec = eAl.col(i) + scores + eaBl.col(t+1);
                prevscores(i) = tempvec.maxCoeff(&maxIndex);
                args(i,t+1) = maxIndex;
            }
            scores = prevscores;
        }

        (scores.array() + epi0.log() + eaBl.col(0).array()).maxCoeff(stateseq);
        for (int t=1; t<T; t++) {
            stateseq[t] = args(stateseq[t-1],t);
        }
    }
}

// NOTE: this class exists for cython binding convenience

template <typename FloatType, typename IntType = int32_t>
class hmmc
{
    public:

    static void messages_backwards_log(
            int M, int T, FloatType *A, FloatType *aBl,
            FloatType *betal)
    { hmm::messages_backwards_log(M,T,A,aBl,betal); }

    static void messages_forwards_log(
            int M, int T, FloatType *A, FloatType *pi0, FloatType *aBl,
            FloatType *alphal)
    { hmm::messages_forwards_log(M,T,A,pi0,aBl,alphal); }

    static void sample_forwards_log(
            int M, int T, FloatType *A, FloatType *pi0, FloatType *aBl, FloatType *betal,
            IntType *stateseq)
    { hmm::sample_forwards_log(M,T,A,pi0,aBl,betal,stateseq); }

    static FloatType messages_forwards_normalized(
            int M, int T, FloatType *A, FloatType *pi0, FloatType *aBl,
            FloatType *alphan)
    { return hmm::messages_forwards_normalized(M,T,A,pi0,aBl,alphan); }

    static void sample_backwards_normalized(
            int M, int T, FloatType *AT, FloatType *alphan,
            IntType *stateseq)
    { hmm::sample_backwards_normalized(M,T,AT,alphan,stateseq); }

    static void viterbi(
            int M, int T, FloatType *A, FloatType *pi0, FloatType *aBl,
            IntType *stateseq)
    { hmm::viterbi(M,T,A,pi0,aBl,stateseq); }
};

#endif
