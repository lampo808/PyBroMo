#
# PyBroMo - A single molecule diffusion simulator in confocal geometry.
#
# Copyright (C) 2013-2015 Antonino Ingargiola tritemio@gmail.com
#

"""
This module contains the core classes and functions to perform the
Brownian motion and timestamps simulation.
"""

from __future__ import print_function, absolute_import, division
from builtins import range, zip

import os
import hashlib

import numpy as np
from numpy import array, sqrt

from .storage import Storage
from .iter_chunks import iter_chunksize, iter_chunk_index


## Avogadro constant
NA = 6.022141e23    # [mol^-1]


def get_seed(seed, ID=0, EID=0):
    """Get a random seed that is a combination of `seed`, `ID` and `EID`.
    Provides different, but deterministic, seeds in parallel computations
    """
    return seed + EID + 100 * ID

def hash_(x):
    return hashlib.sha1(repr(x).encode()).hexdigest()

class Box:
    """The simulation box"""
    def __init__(self, x1, x2, y1, y2, z1, z2):
        self.x1, self.x2 = x1, x2
        self.y1, self.y2 = y1, y2
        self.z1, self.z2 = z1, z2
        self.b = array([[x1, x2], [y1, y2], [z1, z2]])

    @property
    def volume(self):
        """Box volume in m^3."""
        return (self.x2 - self.x1) * (self.y2 - self.y1) * (self.z2 - self.z1)

    @property
    def volume_L(self):
        """Box volume in liters."""
        return self.volume * 1e3

    def __repr__(self):
        return u"Box: X %.1fum, Y %.1fum, Z %.1fum" % (
            (self.x2 - self.x1) * 1e6,
            (self.y2 - self.y1) * 1e6,
            (self.z2 - self.z1) * 1e6)


class Particle(object):
    """Class to describe a single particle."""
    def __init__(self, D, x0=0, y0=0, z0=0):
        self.D = D   # diffusion coefficient in SI units, m^2/s
        self.x0, self.y0, self.z0 = x0, y0, z0
        self.r0 = array([x0, y0, z0])


class Particles(object):
    """A list of Particle() objects and a few attributes."""

    @staticmethod
    def generate(N, box, D, rs=None, seed=1):
        """Generate `N` Particle() objects with random position in `box`.

        Arguments:
            N (int): number of particles to be generated
            box (Box object): the simulation box
            rs (RandomState object): random state object used as random number
                generator. If None, use a random state initialized from seed.
            seed (uint): when `rs` is None, `seed` is used to initialize the
                random state, otherwise is ignored.
        """
        if rs is None:
            rs = np.random.RandomState(seed=seed)
        init_random_state = rs.get_state()
        X0 = rs.rand(N) * (box.x2 - box.x1) + box.x1
        Y0 = rs.rand(N) * (box.y2 - box.y1) + box.y1
        Z0 = rs.rand(N) * (box.z2 - box.z1) + box.z1
        part = [Particle(D=D, x0=x0, y0=y0, z0=z0)
                for x0, y0, z0 in zip(X0, Y0, Z0)]
        return Particles(part, init_random_state=init_random_state)

    def __init__(self, list_of_particles, init_random_state=None):
        self._plist = list_of_particles
        self.init_random_state = init_random_state
        self.rs_hash = hash_(init_random_state)[:3]

    def __iter__(self):
        return iter(self._plist)

    def __len__(self):
        return len(self._plist)

    def __item__(self, i):
        return self._plist[i]

    def __add__(self, other_particles):
        return Particles(self._plist + other_particles._plist,
                         init_random_state=self.init_random_state)

    @property
    def diffusion_coeff(self):
        return np.array([par.D for par in self])

    @property
    def diffusion_coeff_counts(self):
        diff_coeff, counts = np.unique(self.diffusion_coeff, return_counts=True)
        return [(D, n) for D, n in zip(diff_coeff, counts)]

    def short_repr(self):
        s = ["P%d_D%.2g" % (n, D) for D, n in self.diffusion_coeff_counts]
        return "_".join(s)

    def __repr__(self):
        s = ["#Particles: %d D: %.2g" % (n, D)
             for D, n in self.diffusion_coeff_counts]
        return ", ".join(s)


def wrap_periodic(a, a1, a2):
    """Folds all the values of `a` outside [a1..a2] inside that intervall.
    This function is used to apply periodic boundary conditions.
    """
    a -= a1
    wrapped = np.mod(a, a2 - a1) + a1
    return wrapped

def wrap_mirror(a, a1, a2):
    """Folds all the values of `a` outside [a1..a2] inside that intervall.
    This function is used to apply mirror-like boundary conditions.
    """
    a[a > a2] = a2 - (a[a > a2] - a2)
    a[a < a1] = a1 + (a1 - a[a < a1])
    return a


class ParticlesSimulation(object):
    """Class that performs the Brownian motion simulation of N particles.
    """
    def __init__(self, t_step, t_max, particles, box, psf, EID=0, ID=0):
        """Initialize the simulation parameters.

        Arguments:
            D (float): diffusion coefficient (m/s^2)
            t_step (float): simulation time step (seconds)
            t_max (float): simulation time duration (seconds)
            particles (Particles object): initial particle position
            box (Box object): the simulation boundaries
            psf (GaussianPSF or NumericPSF object): the PSF used in simulation
            EID (int): index for the engine on which the simulation is ran.
                Used to distinguish simulations when using parallel computing.
            ID (int): an index for the simulation. Can be used to distinguish
                simulations that are run multiple times.

        Note that EID and ID are shown in the string representation and are
        used to save unique file names.
        """
        self.particles = particles
        self.box = box
        self.psf = psf
        self.t_step = t_step
        self.t_max = t_max
        self.ID = ID
        self.EID = EID
        self.n_samples = int(t_max / t_step)

    @property
    def diffusion_coeff(self):
        return np.array([par.D for par in self.particles])

    @property
    def num_particles(self):
        return len(self.particles)

    @property
    def sigma_1d(self):
        return [np.sqrt(2 * par.D * self.t_step) for par in self.particles]

    def __repr__(self):
        pM = self.concentration(pM=True)
        s = repr(self.box)
        s += "\n%s, %.1f pM, t_step %.1fus, t_max %.1fs" %\
             (self.particles, pM, self.t_step * 1e6, self.t_max)
        s += " ID_EID %d %d" % (self.ID, self.EID)
        return s

    def hash(self):
        """Return an hash for the simulation parameters (excluding ID and EID)
        This can be used to generate unique file names for simulations
        that have the same parameters and just different ID or EID.
        """
        hash_numeric = 't_step=%.3e, t_max=%.2f, np=%d, conc=%.2e' % \
            (self.t_step, self.t_max, self.num_particles, self.concentration())
        hash_list = [hash_numeric, self.particles.short_repr(), repr(self.box),
                     self.psf.hash()]
        return hashlib.md5(repr(hash_list).encode()).hexdigest()

    def compact_name_core(self, hashdigits=6, t_max=False):
        """Compact representation of simulation params (no ID, EID and t_max)
        """
        Moles = self.concentration()
        name = "%s_%dpM_step%.1fus" % (
            self.particles.short_repr(), Moles * 1e12, self.t_step * 1e6)
        if hashdigits > 0:
            name = self.hash()[:hashdigits] + '_' + name
        if t_max:
            name += "_t_max%.1fs" % self.t_max
        return name

    def compact_name(self, hashdigits=6):
        """Compact representation of all simulation parameters
        """
        # this can be made more robust for ID > 9 (double digit)
        s = self.compact_name_core(hashdigits, t_max=True)
        s += "_ID%d-%d" % (self.ID, self.EID)
        return s

    @property
    def numeric_params(self):
        """A dict containing all the simulation numeric-parameters.

        The values are 2-element tuples: first element is the value and
        second element is a string describing the parameter (metadata).
        """
        nparams = dict(
            D = (self.diffusion_coeff.mean(), 'Diffusion coefficient (m^2/s)'),
            np = (self.num_particles, 'Number of simulated particles'),
            t_step = (self.t_step, 'Simulation time-step (s)'),
            t_max = (self.t_max, 'Simulation total time (s)'),
            ID = (self.ID, 'Simulation ID (int)'),
            EID = (self.EID, 'IPython Engine ID (int)'),
            pico_mol = (self.concentration() * 1e12,
                        'Particles concentration (pM)'))
        return nparams

    def print_sizes(self):
        """Print on-disk array sizes required for current set of parameters."""
        float_size = 4
        MB = 1024 * 1024
        size_ = self.n_samples * float_size
        em_size = size_ * self.num_particles / MB
        pos_size = 3 * size_ * self.num_particles / MB
        print("  Number of particles:", self.num_particles)
        print("  Number of time steps:", self.n_samples)
        print("  Emission array - 1 particle (float32): %.1f MB" % (size_ / MB))
        print("  Emission array (float32): %.1f MB" % em_size)
        print("  Position array (float32): %.1f MB " % pos_size)

    def concentration(self, pM=False):
        """Return the concentration (in Moles) of the particles in the box.
        """
        concentr = (self.num_particles / NA) / self.box.volume_L
        if pM:
            concentr *= 1e12
        return concentr

    def reopen_store(self):
        """Reopen a closed store in read-only mode."""
        self.store.open()
        self.psf_pytables = psf_pytables
        self.emission = S.store.data_file.root.trajectories.emission
        self.emission_tot = S.store.data_file.root.trajectories.emission_tot
        self.chunksize = S.store.data_file.get_node('/parameters', 'chunksize')

    def _save_group_attr(self, group, attr_name, attr_value):
        """Save attribute `attr_name` containing `attr_value` in `group`.
        """
        group = self.store.data_file.get_node(group)
        group._v_attrs[attr_name] = attr_value

    def _load_group_attr(self, group, attr_name):
        """Load attribute `attr_name` from `group`.
        """
        group = self.store.data_file.get_node(group)
        return group._v_attrs[attr_name]

    def open_store(self, prefix='pybromo_', chunksize=2**19, chunkslice='bytes',
                   comp_filter=None, overwrite=True):
        """Open and setup the on-disk storage file (pytables HDF5 file).

        Arguments:
            prefix (string): file-name prefix for the HDF5 file
            chunksize (int): chunk size used for the on-disk arrays saved
                during the brownian motion simulation. Does not apply to
                the timestamps arrays (see :method:``).
            chunkslice ('times' or 'bytes'): if 'bytes' (default) the chunksize
                is taken as the size in bytes of the chunks. Else, if 'times'
                chunksize is the size of the last dimension. In this latter
                case 2-D or 3-D arrays have bigger chunks than 1-D arrays.
            comp_filter (tables.Filter or None): compression filter to use
                for the on-disk arrays saved during the brownian motion
                simulation.
            overwrite (bool): if True, overwrite the file if already exists.
                All the previoulsy stored data in that file will be lost.
        """
        nparams = self.numeric_params
        self.chunksize = chunksize
        nparams.update(chunksize=(chunksize, 'Chunksize for arrays'))
        self.store_fname = prefix + self.compact_name() + '.hdf5'

        attr_params = dict(particles=self.particles, box=self.box)
        self.store = Storage(self.store_fname, nparams=nparams,
                             attr_params=attr_params, overwrite=overwrite)

        self.psf_pytables = self.psf.to_hdf5(self.store.data_file, '/psf')
        self.store.data_file.create_hard_link('/psf', 'default_psf',
                                              target=self.psf_pytables)
        # Note psf.fname is the psf name in `data_file.root.psf`
        self._save_group_attr('/trajectories', 'psf_name', self.psf.fname)
        self.traj_group = self.store.data_file.root.trajectories
        self.ts_group = self.store.data_file.root.timestamps

        kwargs = dict(chunksize=self.chunksize, chunkslice=chunkslice)
        if comp_filter is not None:
            kwargs.update(comp_filter=comp_filter)
        self.emission_tot = self.store.add_emission_tot(**kwargs)
        self.emission = self.store.add_emission(**kwargs)
        self.position = self.store.add_position(**kwargs)

    def _sim_trajectories(self, time_size, start_pos, rs,
                          total_emission=False, save_pos=False,
                          wrap_func=wrap_periodic):
        """Simulate (in-memory) `time_size` steps of trajectories.

        Simulate Brownian motion diffusion and emission of all the particles.
        Uses the attrbutes: num_particles, sigma_1d, box, psf.

        Arguments:
            time_size (int): number of time steps to be simulated.
            start_pos (array): shape (num_particles, 3), particles start
                positions. This array is modified to store the end position
                after this method is called.
            rs (RandomState): a `numpy.random.RandomState` object used
                to generate the random numbers.
            total_emission (bool): if True, store only the total emission array
                containing the sum of emission of all the particles.
            save_pos (bool): if True, save the particles 3D trajectories
            wrap_func (function): the function used to apply the boundary
                condition (use :func:`wrap_periodic` or :func:`wrap_mirror`).

        Returns:
            POS (list): list of 3D trajectories arrays (3 x time_size)
            em (array): array of emission (total or per-particle)
        """
        num_particles = self.num_particles
        if total_emission:
            em = np.zeros((time_size), dtype=np.float32)
        else:
            em = np.zeros((num_particles, time_size), dtype=np.float32)

        POS = []
        # pos_w = np.zeros((3, c_size))
        for i, sigma_1d in enumerate(self.sigma_1d):
            delta_pos = rs.normal(loc=0, scale=sigma_1d,
                                  size=3 * time_size)
            delta_pos = delta_pos.reshape(3, time_size)
            pos = np.cumsum(delta_pos, axis=-1, out=delta_pos)
            pos += start_pos[i]

            # Coordinates wrapping using periodic boundary conditions
            for coord in (0, 1, 2):
                pos[coord] = wrap_func(pos[coord], *self.box.b[coord])

            # Sample the PSF along i-th trajectory then square to account
            # for emission and detection PSF.
            Ro = sqrt(pos[0]**2 + pos[1]**2)  # radial pos. on x-y plane
            Z = pos[2]
            current_em = self.psf.eval_xz(Ro, Z)**2
            if total_emission:
                # Add the current particle emission to the total emission
                em += current_em.astype(np.float32)
            else:
                # Store the individual emission of current particle
                em[i] = current_em.astype(np.float32)
            if save_pos:
                POS.append(pos.reshape(1, 3, time_size))
            # Save last position as next starting position
            start_pos[i] = pos[:, -1:]
        return POS, em

    def simulate_diffusion(self, save_pos=False, total_emission=True,
                           rs=None, seed=1, wrap_func=wrap_periodic,
                           verbose=True, chunksize=2**19, chunkslice='bytes'):
        """Simulate Brownian motion trajectories and emission rates.

        This method performs the Brownian motion simulation using the current
        set of parameters. Before running this method you can check the
        disk-space requirements using :method:`print_sizes`.

        Results are stored to disk in HDF5 format and are accessible in
        in `self.emission`, `self.emission_tot` and `self.position` as
        pytables arrays.

        Arguments:
            save_pos (bool): if True, save the particles 3D trajectories
            total_emission (bool): if True, store only the total emission array
                containing the sum of emission of all the particles.
            rs (RandomState object): random state object used as random number
                generator. If None, use a random state initialized from seed.
            seed (uint): when `rs` is None, `seed` is used to initialize the
                random state, otherwise is ignored.
            wrap_func (function): the function used to apply the boundary
                condition (use :func:`wrap_periodic` or :func:`wrap_mirror`).
            verbose (bool): if False, prints no output.
        """
        if rs is None:
            rs = np.random.RandomState(seed=seed)

        if 'store' not in self.__dict__:
            self.open_store(chunksize=chunksize, chunkslice=chunkslice)
        # Save current random state for reproducibility
        self._save_group_attr('/trajectories', 'init_random_state',
                              rs.get_state())

        em_store = self.emission_tot if total_emission else self.emission

        if verbose:
            print('[PID %d] Simulation chunk:' % os.getpid(), end='')
        i_chunk = 0
        t_chunk_size = self.emission.chunkshape[1]

        par_start_pos = [p.r0 for p in self.particles]
        par_start_pos = (np.vstack(par_start_pos)
                         .reshape(self.num_particles, 3, 1))
        for time_size in iter_chunksize(self.n_samples, t_chunk_size):
            if verbose:
                print('.', end='')

            POS, em = self._sim_trajectories(time_size, par_start_pos, rs,
                                             total_emission=total_emission,
                                             save_pos=save_pos,
                                             wrap_func=wrap_func)

            ## Append em to the permanent storage
            # if total_emission, data is just a linear array
            # otherwise is a 2-D array (self.num_particles, c_size)
            em_store.append(em)
            if save_pos:
                self.position.append(np.vstack(POS).astype('float32'))
            i_chunk += 1

        # Save current random state
        self._save_group_attr('/trajectories', 'last_random_state',
                              rs.get_state())
        self.store.data_file.flush()

    def _get_ts_name_core(self, max_rate, bg_rate):
        return 'max_rate%dkcps_bg%dcps' % (max_rate * 1e-3, bg_rate)

    def _get_ts_name(self, max_rate, bg_rate, rs_state, hashsize=4):
        return self._get_ts_name_core(max_rate, bg_rate) + \
            '_rs_%s' % hash_(rs_state)[:hashsize]

    def get_timestamp(self, max_rate, bg_rate):
        ts, ts_par = [], []
        name = self._get_ts_name_core(max_rate, bg_rate)
        for node in self.ts_group._f_list_nodes():
            if name in node.name:
                if node.name.endswith('_par'):
                    ts_par.append(node)
                else:
                    ts.append(node)
        if len(ts) == 0:
            raise ValueError("No array matching '%s'" % name)
        elif len(ts) > 1:
            print('WARNING: multiple matches, only the first is returned.')
        return ts[0], ts_par[0]

    def timestamp_names(self):
        names = []
        for node in self.ts_group._f_list_nodes():
            if node.name.endswith('_par'): continue
            names.append(node.name)
        return names

    def simulate_timestamps(self, max_rate=1, bg_rate=0, rs=None, seed=1,
                            chunksize=2**16, comp_filter=None,
                            overwrite=False):
        """Compute timestamps and particles arrays and store results to disk.

        The results are accessible as pytables arrays in `.timestamps` and
        `.tparticles`. The background generated timestamps are assigned a
        conventional particle number (last particle index + 1).

        Arguments:
            max_rate (float, cps): max emission rate for a single particle
            bg_rate (float, cps): rate for a Poisson background process
            chunksize (int): chunk size used for the on-disk timestamp array
            comp_filter (tables.Filter or None): compression filter to use
                for the on-disk `timestamps` and `tparticles` arrays.
            rs (RandomState object): random state object used as random number
                generator. If None, use a random state initialized from seed.
            seed (uint): when `rs` is None, `seed` is used to initialize the
                random state, otherwise is ignored.
        """
        if rs is None:
            rs = np.random.RandomState(seed=seed)
            # Try to set the random state from the last session to preserve
            # a single random stream when simulating timestamps multiple times
            ts_attrs = self.store.data_file.root.timestamps._v_attrs
            if 'last_random_state' in ts_attrs._f_list():
                rs.set_state(ts_attrs['last_random_state'])
                print("INFO: Random state set to last saved state"
                      " in '/timestamps'.")
            else:
                print("INFO: Random state initialized from seed (%d)." % seed)

        fractions = [5, 2, 8, 4, 9, 1, 7, 3, 6, 9, 0, 5, 2, 8, 4, 9]
        scale = 10
        max_counts = 4

        name = self._get_ts_name(max_rate, bg_rate, rs.get_state())
        self.timestamps, self.tparticles = self.store.add_timestamps(
                name = name,
                clk_p = self.t_step / scale,
                max_rate = max_rate,
                bg_rate = bg_rate,
                num_particles = self.num_particles,
                bg_particle = self.num_particles,
                overwrite = overwrite,
                chunksize = chunksize,
                comp_filter = comp_filter)
        self.timestamps.set_attr('init_random_state', rs.get_state())

        # Load emission in chunks, and save only the final timestamps
        for i_start, i_end in iter_chunk_index(self.n_samples,
                                               self.emission.chunkshape[1]):
            counts_chunk = sim_timetrace_bg(
                self.emission[:, i_start:i_end], max_rate, bg_rate,
                self.t_step, rs=rs)
            index = np.arange(0, counts_chunk.shape[1])

            # Loop for each particle to compute timestamps
            times_chunk_p = []      # <-- Try preallocating array
            par_index_chunk_p = []  # <-- Try preallocating array
            for p_i, counts_chunk_p_i in enumerate(counts_chunk.copy()):
                # Compute timestamps for paricle p_i for all bins with counts
                times_c_i = [(index[counts_chunk_p_i >= 1] + i_start) * scale]
                # Additional timestamps for bins with counts > 1
                for frac, v in zip(fractions, range(2, max_counts + 1)):
                    times_c_i.append(
                        (index[counts_chunk_p_i >= v] + i_start) * scale + frac)

                # Stack the arrays from different "counts"
                t = np.hstack(times_c_i)
                times_chunk_p.append(t)
                par_index_chunk_p.append(np.full(t.size, p_i, dtype='u1'))

            # Merge the arrays of different particles
            times_chunk_s = np.hstack(times_chunk_p)  # <-- Try preallocating
            par_index_chunk_s = np.hstack(par_index_chunk_p)  # <-- this too

            # Sort timestamps inside the merged chunk
            index_sort = times_chunk_s.argsort(kind='mergesort')
            times_chunk_s = times_chunk_s[index_sort]
            par_index_chunk_s = par_index_chunk_s[index_sort]

            # Save (ordered) timestamps and corrensponding particles
            self.timestamps.append(times_chunk_s)
            self.tparticles.append(par_index_chunk_s)

        # Save current random state so it can be resumed in the next session
        self._save_group_attr('/timestamps', 'last_random_state',
                              rs.get_state())
        self.store.data_file.flush()

def sim_timetrace(emission, max_rate, t_step):
    """Draw random emitted photons from Poisson(emission_rates).
    """
    emission_rates = emission * max_rate * t_step
    return np.random.poisson(lam=emission_rates).astype(np.uint8)

def sim_timetrace_bg(emission, max_rate, bg_rate, t_step, rs=None):
    """Draw random emitted photons from Poisson(emission_rates).
    Return an uint8 array of counts with shape[0] == emission.shape[0] + 1.
    The last row is a "fake" particle representing Poisson background.
    """
    if rs is None:
        rs = np.random.RandomState()
    em = np.atleast_2d(emission).astype('float64', copy=False)
    counts = np.zeros((em.shape[0] + 1, em.shape[1]), dtype='u1')
    # In-place computation
    # NOTE: the caller will see the modification
    em *= (max_rate * t_step)
    # Use automatic type conversion int64 -> uint8
    counts[:-1] = rs.poisson(lam=em)
    counts[-1] = rs.poisson(lam=bg_rate * t_step, size=em.shape[1])
    return counts

def sim_timetrace_bg2(emission, max_rate, bg_rate, t_step, rs=None):
    """Draw random emitted photons from Poisson(emission_rates).
    Return an uint8 array of counts with shape[0] == emission.shape[0] + 1.
    The last row is a "fake" particle representing Poisson background.
    """
    if rs is None:
        rs = np.random.RandomState()
    emiss_bin_rate = np.zeros((emission.shape[0] + 1, emission.shape[1]),
                              dtype='float64')
    emiss_bin_rate[:-1] = emission * max_rate * t_step
    emiss_bin_rate[-1] = bg_rate * t_step
    counts = rs.poisson(lam=emiss_bin_rate).astype('uint8')
    return counts

def parallel_gen_timestamps(dview, max_em_rate, bg_rate):
    """Generate timestamps from a set of remote simulations in `dview`.
    Assumes that all the engines have an `S` object already containing
    an emission trace (`S.em`). The "photons" timestamps are generated
    from these emission traces and merged into a single array of timestamps.
    `max_em_rate` and `bg_rate` are passed to `S.sim_timetrace()`.
    """
    dview.execute('S.sim_timestamps_em_store(max_rate=%d, bg_rate=%d, '
                  'seed=S.EID, overwrite=True)' % (max_em_rate, bg_rate))
    dview.execute('times = S.timestamps[:]')
    dview.execute('times_par = S.timestamps_par[:]')
    Times = dview['times']
    Times_par = dview['times_par']
    # Assuming all t_max equal, just take the first
    t_max = dview['S.t_max'][0]
    t_tot = np.sum(dview['S.t_max'])
    dview.execute("sim_name = S.compact_name_core(t_max=False, hashdigit=0)")
    # Core names contains no ID or t_max
    sim_name = dview['sim_name'][0]
    times_all, times_par_all = merge_ph_times(Times, Times_par,
                                              time_block=t_max)
    return times_all, times_par_all, t_tot, sim_name