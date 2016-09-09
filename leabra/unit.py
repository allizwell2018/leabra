"""
Implementation of a Leabra Unit, as described in the CECN1 textbook,
and reproducing the behavior of emergent 5.0 units.

We implement only the rate-coded version. The code is intended to be
as simple as possible to understand. It is not in any way optimized
for performance.
"""
import copy

import numpy as np
import scipy.interpolate



class Unit:
    """Leabra Unit (as implemented in emergent 5.0)"""

    def __init__(self, spec=None):
        """
        spec:  UnitSpec instance with custom values for the unit parameters.
               If None, default values will be used.
        """
        self.spec = spec
        if self.spec is None:
            self.spec = UnitSpec()

        self.ex_inputs  = []    # excitatory inputs for the next cycle
        self.forced_act = False # Is activity directly set?

        self.g_e   = 0
        self.I_net = 0
        self.v_m   = 0.15
        self.act   = 0     # current activity
        self.act_m = 0     # activity at the end of the minus phase

        self.logs  = {'net': [], 'act': [], 'I_net': [], 'v_m': []}


    def cycle(self, g_i=0.0, dt_integ=1):
        """Cycle the unit"""
        return self.spec.cycle(self, g_i=g_i, dt_integ=dt_integ)

    def calculate_net_in(self):
        return self.spec.calculate_net_in(self)


    @property
    def net(self):
        """Excitatory conductance."""
        return self.spec.g_bar_e * self.g_e


    def add_excitatory(self, inp_act, forced=False):
        """Add an input for the next cycle.

        If the activity is directly set (`forced==True`), then at most one call
        to add_excitatory should be done per cycle. If no call is made and the
        last call was forced, then the subsequent cycles continue to force this
        value on the unit activity.
        """
        self.forced = forced
        if self.forced: # the activity is set directly
            assert len(self.ex_inputs) == 0
            self.forced_act = inp_act
        else:
            self.ex_inputs.append(inp_act)


    def update_logs(self):
        """Record current state. Called after each cycle."""
        self.logs['net'].append(self.net)
        self.logs['I_net'].append(self.I_net)
        self.logs['v_m'].append(self.v_m)
        self.logs['act'].append(self.act)


    def show_config(self):
        """Display the value of constants and state variables."""
        print('Parameters:')
        for name in ['dt_vm', 'dt_net', 'g_l', 'g_bar_e', 'g_bar_l', 'g_bar_i',
                     'e_rev_e', 'e_rev_l', 'e_rev_i', 'act_thr', 'act_gain']:
            print('   {}: {:.2f}'.format(name, getattr(self.spec, name)))
        print('State:')
        for name in ['g_e', 'I_net', 'v_m', 'act']:
            print('   {}: {:.2f}'.format(name, getattr(self, name)))



class UnitSpec:
    """Units specification.

    Each unit can have different parameters values. They don't change during
    cycles, and unless you know what you're doing, you should not change them
    after the Unit creation. The best way to proceed is to create the UnitSpec,
    modify it, and provide the spec when instantiating a Unit:

    >>> spec = UnitSpec(act_thr=0.35) # specifying parameters at instantiation
    >>> spec.bias = 0.5               # you can also do it afterward
    >>> u = Unit(spec=spec)           # creating a Unit instance

    """

    def __init__(self, **kwargs):
        # time step constants
        self.dt_net    = 0.7   # for net update (net = g_e * g_bar_e) (eq. 2.8)
        self.dt_vm     = 0.1   # for vm update (eq. 2.16)
        # input channels parameters (eq. 2.8)
        self.g_l       = 1.0   # leak current (constant)
        self.g_bar_e   = 0.4   # excitatory maximum conductance
        self.g_bar_i   = 1.0   # inhibitory maximum conductance
        self.g_bar_l   = 2.8   # leak maximum conductance
        # reversal potential (eq. 2.8)
        self.e_rev_e   = 1.0   # excitatory
        self.e_rev_i   = 0.15  # inhibitory
        self.e_rev_l   = 0.15  # leak
        # activation function parameters (eq. 2.19)
        self.act_thr   = 0.25  # threshold
        self.act_gain  = 600   # gain

        self.bias      = 0.0

        self.noisy_act = False # If True, uses the noisy activation function (eq A5)
        self.act_sd    = 0.005 # standard deviation of the noisy gaussian (eq A5)

        for key, value in kwargs.items():
            setattr(self, key, value)

        self._nxx1_conv = None # precomputed convolution for the noisy xx1 function


    def xx1(self, v_m):
        """Compute the x/(x+1) function."""
        X = self.act_gain * max((v_m - self.act_thr), 0.0)
        return X / (X + 1) # eq 2.19


    def noisy_xx1(self, v_m):
        """Compute the noisy x/(x+1) function.

        The noisy x/(x+1) function is the convolution of the x/(x+1) function
        with a Gaussian with a `self.spec.act_sd` standard deviation. Here, we
        precompute the convolution as a look-up table, and interpolate it with
        the desired point every time the function is called.
        """
        if self._nxx1_conv is None:  # convolution not precomputed yet
            xs = np.linspace(-2.0, 2.0, 2000)  # x represents (self.v_m - self.spec.act_thr)
            X  = self.act_gain * np.maximum(xs, 0)
            xx1 = X / (X + 1)  # regular x/(x+1) function over xs

            gaussian = (np.exp(-xs**2 / (2 * self.act_sd**2)) /
                        (self.act_sd * np.sqrt(2 * np.pi)))

            conv = np.convolve(xx1, gaussian, mode='same') / np.sum(gaussian)
            self._nxx1_conv = xs, conv

        x = v_m - self.act_thr
        xs, conv = self._nxx1_conv
        return float(scipy.interpolate.interp1d(xs, conv, kind='linear',
                                                fill_value='extrapolate')(x))


    def calculate_net_in(self, unit, dt_integ=1):
        """Calculate the net input for the unit. To execute before cycle()"""
        if unit.forced:
            unit.act = unit.forced_act
            return # done!

        # computing net_raw, the total, instantaneous, excitatory input for the neuron
        net_raw = sum(unit.ex_inputs) # / max(1, len(self.ex_inputs))
        unit.ex_inputs = []

        # updating net
        unit.g_e += dt_integ * self.dt_net * (net_raw - unit.g_e)  # eq 2.16


    def cycle(self, unit, g_i=0.0, dt_integ=1):
        """Update activity

        unit    :  the unit to cycle
        g_i     :  inhibitory input
        dt_integ:  integration time step, in ms.
        """

        if unit.forced:
            return # done!

        # computing I_net
        gc_e = self.g_bar_e * unit.g_e
        gc_i = self.g_bar_i * g_i
        gc_l = self.g_bar_l * self.g_l
        unit.I_net = (  gc_e * (self.e_rev_e - unit.v_m)  # eq 2.8
                      + gc_i * (self.e_rev_i - unit.v_m)
                      + gc_l * (self.e_rev_l - unit.v_m))

        # updating v_m
        unit.v_m += dt_integ * self.dt_vm * unit.I_net  # eq 2.8

        # updating activity
        if self.noisy_act:
            unit.act = self.noisy_xx1(unit.v_m)
        else:
            unit.act = self.xx1(unit.v_m)

        unit.update_logs()
