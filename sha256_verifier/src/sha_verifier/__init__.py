import os

# The verifier parallelises over processes and never uses numpy's linear algebra, so the
# thread pools that numpy's BLAS would start are pure overhead: dozens of idle threads in
# every worker, present whenever the process forks. Keep them to one thread each unless
# the caller has said otherwise. This must run before numpy is first imported.
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_variable, '1')

__version__ = "0.1.0"
