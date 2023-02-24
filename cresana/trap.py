

"""

Author: F. Thomas
Date: August 11, 2021

"""

__all__ = []

from abc import ABC, abstractmethod
import warnings
from warnings import warn
warnings.simplefilter('default')


from scipy.signal import sawtooth, square
from scipy.optimize import root_scalar
from scipy.integrate import cumtrapz, quad
from scipy.interpolate import make_interp_spline
import numpy as np

from .physicsconstants import speed_of_light, E0_electron
from .utility import get_pos
from .electronsim import ElectronSim
from .cyclotronphysics import get_energy, get_omega_cyclotron, get_v_gradB, get_relativistic_velocity


def magnetic_moment(E_kin, pitch, B0):
    return E_kin * np.sin(pitch)**2/B0

def get_integrated_phase(w, t):
    return cumtrapz(w, x=t, initial=0.0)    

class Trap(ABC):
    
    def __init__(self, add_gradB=True):
        self.add_gradB = add_gradB

    @abstractmethod
    def trajectory(self, electron):
        pass

    @abstractmethod
    def B_field(self, r, z):
        pass
        
    @abstractmethod
    def get_f(self, electron):
        pass
        
    @abstractmethod
    def get_grad_mag(self, electron, z):
        pass
        
    def get_pitch_sign(self, electron, t):
        T = 1/self.get_f(electron)
        sign = np.ones_like(t)
        period_fraction = (t%T)/T
        sign[(period_fraction<0.25)|(period_fraction>0.75)] = -1
        
        return sign
        
    def get_pitch(self, electron, t, B):
        theta_0 = electron.pitch
        B0 = np.min(B)
        sign = self.get_pitch_sign(electron,t)
        #there seems to be a numerics issue here -> round to 12 digits
        #without that observed sintheta>1, which results in NaN
        sintheta = np.around(np.sin(theta_0)*np.sqrt(B/B0),10)
        theta = np.pi/2 - np.arcsin(sintheta)
        theta = sign*theta + np.pi/2
        return theta
        
    def add_gradB_motion(self, electron, v_gradB, t):
        
        r = electron.r
        phi = np.arctan2(electron._y0, electron._x0)
        
        if r>0:
            w_gradB = v_gradB/r
        else:
            w_gradB = np.zeros_like(v_gradB)
            
        phase_gradB = get_integrated_phase(w_gradB, t)
        
        return r*np.cos(phase_gradB+phi), r*np.sin(phase_gradB+phi)
        
    def simulate(self, electron):
        
        coords_f = self.trajectory(electron)
        
        def f(t):
            coords = coords_f(t)
            B, grad = self.get_grad_mag(electron, coords[...,2])
            pitch = self.get_pitch(electron, t, B)
            
            E_kin = get_energy(electron.E_kin, t, B, pitch)
        
            w = get_omega_cyclotron(B, E_kin)
            v_gradB = get_v_gradB(E_kin, pitch, B, w, grad)
            
            if self.add_gradB:
                coords[...,0], coords[...,1] = self.add_gradB_motion(electron, v_gradB, t)
            
            return coords, pitch, B, E_kin, w
        
        return f

def harmonic_potential(r, z, B0, L0):
    a1 = B0
    a3 = B0/(3*L0**2)
    return a1 - 3/2*a3*(r**2 - 2*z**2)
    
    
def harmonic_Br(r, z, B0, L0):
    a3 = B0/(3*L0**2)
    return -3*r*z*a3
    

def flat_potential(z, B0):
    if type(z) == np.ndarray:
        potential = np.full(z.shape, B0)
    else:
        potential = np.array([B0])

    return potential
    

def get_z_harmonic(t, z_max, omega, phi):
    return z_max*np.sin(omega*t + phi)
        
        
def get_vz_harmonic(t, z_max, omega, phi):
    return z_max*omega*np.cos(omega*t + phi)
    

def get_z_flat(t, z_max, omega, phi):
    return z_max*sawtooth(t*omega + np.pi/2 + phi, width=0.5)
        

def get_omega_harmonic(v0, pitch, r, L0):
    return v0*np.sin(pitch)/L0*np.sqrt(1/(1-r**2/(2*L0**2)))
    

def get_z_max_harmonic(L0, pitch, r):
    return np.sqrt(L0**2-0.5*r**2)/np.tan(pitch)
    

class HarmonicTrap(Trap):

    def __init__(self, B0, L0, add_gradB=True):
        Trap.__init__(self, add_gradB)
        self._B0 = B0
        self._L0 = L0

    def trajectory(self, electron):
        omega = self._get_omega(electron)
        z_max = self._get_z_max(electron)

        phi0 = np.arcsin(electron._z0/z_max)

        return lambda t: get_pos(   np.ones_like(t)*electron._x0,
                                    np.ones_like(t)*electron._y0,
                                    get_z_harmonic(t, z_max, omega, phi0))
                                    
    def B_field(self, r, z):
        """
        the analytic harmonic field solution assumes in its integration that
        B_mag \approx B_z -> B_r is negligible
        However, this is not the case for higher radii
        to prevent more errors with this incorrect solution the derived class method
        B_field needs to provide the B_field that was assumed for the integration and not the actual B_mag
        for the actual B_mag use absolute_B_field
        """
        return harmonic_potential(r, z, self._B0, self._L0)
                        
    def absolute_B_field(self, r, z):
        return np.sqrt(harmonic_potential(r, z, self._B0, self._L0)**2 
                        + harmonic_Br(r, z, self._B0, self._L0)**2)
        
    def pitch(self, electron):
        omega = self._get_omega(electron)
        z_max = self._get_z_max(electron)
        phi0 = np.arcsin(electron._z0/z_max)
        
        def f(t):
            vz = get_vz_harmonic(t, z_max, omega, phi0)
            return np.arccos(vz/electron.v0)
        
        return f

    def _get_omega(self, electron):
        return get_omega_harmonic(electron.v0, electron.pitch, electron.r, self._L0)
        
    def _get_z_max(self, electron):
        return get_z_max_harmonic(self._L0, electron.pitch, electron.r)
        
    def get_f(self, electron):
        return self._get_omega(electron)/(2*np.pi)
        
    def get_grad_mag(self, electron, z):
        r = electron.r
        
        B = self.B_field(r, z)
        grad = self._get_orthogonal_grad(r, z, B)
        
        return B, grad
        
    def _get_orthogonal_grad(self, r, z, B):
        a3 = self._B0/(3*self._L0**2)
        a1 = self._B0
        grad = -0.75*r*a3*(12*r*z*a3 
                        + (2*a1-3*(r**2 - 2*z**2)*a3)
                         *(2*a1 - 3*(r**2 + 4*z**2)*a3))/B**2
        
        return grad

class BoxTrap(Trap):

    def __init__(self, B0, L, add_gradB=True):
        Trap.__init__(self, add_gradB)
        self._B0 = B0
        self._L = L

    def trajectory(self, electron):
        omega = self._get_omega(electron)
        z_max = self._get_z_max()
        phi0 = electron._z0/z_max*np.pi/2

        return lambda t: get_pos(   np.ones_like(t)*electron._x0,
                                    np.ones_like(t)*electron._y0,
                                    get_z_flat(t, z_max, omega, phi0))

    def pitch(self, electron):
        omega = self._get_omega(electron)
        z_max = self._get_z_max()
        phi0 =  electron._z0/z_max*np.pi/2
        
        def f(t):
            delta = np.pi/2 - electron.pitch
            sign = square(t*omega + np.pi/2 + phi0)
            return np.pi/2 - sign*delta
        
        return f
        
    def B_field(self, r, z):
        B = flat_potential(z, self._B0)

        B[z>self._L/2] = np.inf
        B[z<-self._L/2] = np.inf

        return B
        
    def get_grad_mag(self, electron, z):
        r = electron.r
        B = self.B_field(r, z)
        grad = np.zeros_like(B)
        
        return B, grad

    def _get_omega(self, electron):
        return electron.v0*np.cos(electron.pitch)*np.pi/self._L

    def _get_z_max(self):
        return self._L/2

    def get_f(self, electron):
        return self._get_omega(electron)/(2*np.pi)


class BathtubTrap(Trap):

    def __init__(self, B0, L, add_gradB=True):
        warn("'BathtubTrap' is deprecated in this version. It does not support all the features it should.", DeprecationWarning)
        Trap.__init__(self, add_gradB)
        self._B0 = B0
        self._L = L
        self._L0 = L0

    def trajectory(self, electron):
        return lambda t: get_pos(   np.ones_like(t)*electron._x0,
                                    np.ones_like(t)*electron._y0,
                                    self._get_z(electron, t))

    def B_field(self, r, z):
        # in case float input is used
        z_np = np.expand_dims(z, 0)

        B = flat_potential(z_np, self._B0)

        left_harmonic = z_np < -self._L/2
        right_harmonic = z_np > self._L/2

        z_left_harmonic = z_np[left_harmonic] + self._L/2
        z_right_harmonic = z_np[right_harmonic] - self._L/2

        B[left_harmonic] = harmonic_potential(z_left_harmonic, self._B0, self._L0)
        B[right_harmonic] = harmonic_potential(z_right_harmonic, self._B0, self._L0)

        return B[0] #undo the expand_dims in first line

    def _period(self, electron):
        flat_time = self._L/(electron.v0*np.cos(electron.pitch))
        harmonic_time = np.pi/get_omega_harmonic(electron.v0, electron.pitch, self._L0)

        return 2*(flat_time+harmonic_time)

    def _get_z(self, electron, t):
        v_axial = electron.v0 * np.cos(electron.pitch)
        omega = self._get_omega(electron)
        z_max = self._get_z_max(electron)
        
        if abs(electron._z0)>(z_max+self._L/2):
            raise ValueError(f'Electron cannot be trapped at z0={electron._z0} because for pitch={electron._pitch/np.pi*180}° z_max=+-{z_max+self._L/2:.3f}')
        
        T = self._period(electron)

        # z(t=0) = left end of flat region
        t1 = self._L/v_axial # electron reaches right end of flat region -> goes into harmonic region
        t2 = t1 + np.pi/omega # electron reaches right end of flat region again
        t3 = t2 + t1 # electron reaches left end of flat region again -> goes into harmonic region
        
        if abs(electron._z0) < self._L/2:
            t0 = electron._z0/v_axial
        elif electron._z0>0:
            t0 = t1/2 + 1/omega*np.arcsin((electron._z0 - self._L/2)/z_max)
        else:
            t0 = -t1/2 - 1/omega*np.arcsin((-electron._z0 - self._L/2)/z_max)

        t = t + t1/2 + t0 #zero point shifted such that z(0) = z0
        t = t%T # z periodic with T

        first_flat = t<=t1
        right_harmonic = (t>t1)&(t<=2)
        second_flat = (t>t2)&(t<=t3)
        left_harmonic = t>t3
        
        z = np.zeros(t.shape)
        z[first_flat] = -self._L/2 + v_axial*t[first_flat]
        z[right_harmonic] = self._L/2 + z_max * np.sin(omega*(t[right_harmonic] - t1))
        z[second_flat] = self._L/2 - v_axial*(t[second_flat] - t2)
        z[left_harmonic] = -self._L/2 - z_max * np.sin(omega*(t[left_harmonic] - t3))

        return z
        
    def pitch(self, electron):
        v_axial = electron.v0 * np.cos(electron.pitch)
        omega = self._get_omega(electron)
        z_max = self._get_z_max(electron)
        
        if abs(electron._z0)>(z_max+self._L/2):
            raise ValueError(f'Electron cannot be trapped at z0={electron._z0} because for pitch={electron._pitch/np.pi*180}° z_max=+-{z_max+self._L/2:.3f}')
        
        T = self._period(electron)

        # z(t=0) = left end of flat region
        t1 = self._L/v_axial # electron reaches right end of flat region -> goes into harmonic region
        t2 = t1 + np.pi/omega # electron reaches right end of flat region again
        t3 = t2 + t1 # electron reaches left end of flat region again -> goes into harmonic region
        
        if abs(electron._z0) < self._L/2:
            t0 = electron._z0/v_axial
        elif electron._z0>0:
            t0 = t1/2 + 1/omega*np.arcsin((electron._z0 - self._L/2)/z_max)
        else:
            t0 = -t1/2 - 1/omega*np.arcsin((-electron._z0 - self._L/2)/z_max)
            
        def f(t):

            t = t + t1/2 + t0 #zero point shifted such that z(0) = z0
            t = t%T # z periodic with T

            first_flat = t<=t1
            right_harmonic = (t>t1)&(t<=2)
            second_flat = (t>t2)&(t<=t3)
            left_harmonic = t>t3
            
            delta = np.pi/2 - electron.pitch
            
            pitch = np.zeros(t.shape)
            pitch[first_flat] = np.pi/2 - delta
            
            vz = get_vz_harmonic(t[right_harmonic] - t1, z_max, omega, 0.)
            pitch[right_harmonic] = np.arccos(vz/electron.v0) # self._L/2 + z_max * np.sin(omega*(t[right_harmonic] - t1))
            
            pitch[second_flat] = np.pi/2 + delta
            
            vz = -get_vz_harmonic(t[left_harmonic] - t3, z_max, omega, 0.)
            pitch[left_harmonic] = np.arccos(vz/electron.v0)
            #pitch[left_harmonic] = -self._L/2 - z_max * np.sin(omega*(t[left_harmonic] - t3))

            return pitch
            
        return f
        
    def get_grad_mag(self, electron, z):
        
        B = self.B_field(r, z)
        grad = np.zeros_like(B)
        
        return B, grad

    def _get_omega(self, electron):
        return get_omega_harmonic(electron.v0, electron.pitch, self._L0)

    def _get_z_max(self, electron):
        return get_z_max_harmonic(self._L0, electron.pitch)

    def get_f(self, electron):
        return 1/self._period(electron)


class ArbitraryTrap(Trap):

    def __init__(self, b_field, add_gradB=True, integration_steps=1000, 
                    root_rtol=0.00001, root_guess_max=10., root_guess_steps=1000):
        Trap.__init__(self, add_gradB)
        self._b_field = b_field
        self._integration_steps = integration_steps
        self._root_rtol = root_rtol
        self._root_guess_max = root_guess_max
        self._root_guess_steps = root_guess_steps
        self._T_buffer = {}

    def trajectory(self, electron):
        _, _, z_f = self._solve_trajectory(electron)

        return lambda t: get_pos(   np.ones_like(t)*electron._x0,
                                    np.ones_like(t)*electron._y0,
                                    z_f(t))

    def B_field(self, r, z):

        pos = np.stack(np.broadcast_arrays(r,z),axis=-1)
        
        B, _ = self._b_field.get_grad_mag(pos)
        return B

    def get_f(self, electron):
        if electron not in self._T_buffer:
            self._solve_trajectory(electron)
            
        T = self._T_buffer[electron]

        return 1/T
        
    def get_grad_mag(self, electron, z):
        r = electron.r
        pos = np.stack((np.ones_like(z)*r,z),axis=-1)
        return self._b_field.get_grad_mag(pos)
        
    def adiabatic_difference(self,electron, z):
        return np.sin(electron.pitch)**2*self.B_field(electron.r, z)-self.B_field(electron.r, 0.)
        
    def guess_root(self, electron):
        z = np.linspace(0, self._root_guess_max, self._root_guess_steps)
        diff = self.adiabatic_difference(electron, z)
        ind = np.argmax(diff>0)
        
        if ind==0:
            raise RuntimeError('Found guess of root at z=0 -> Increase "root_guess_steps" or reduce "root_guess_max"!')
        
        if ind==len(z)-1:
            raise RuntimeError('Found guess of root at z=root_guess_max -> Increase "root_guess_max" or reduce "root_guess_steps"!')
            
        return z[ind-1], z[ind]
        
    def _solve_trajectory(self, electron):
        
        """
        assuming the minimum is at z=0 and the profile is symmetric
        """
        
        root_guess = self.guess_root(electron)
        
        r = electron.r
        
        right = root_scalar(lambda z: self.adiabatic_difference(electron,z), 
                            method='secant', x0=root_guess[0], 
                            x1=root_guess[1], 
                            rtol=self._root_rtol).root
        
        print('zmax', right)
        
        z_val = np.linspace(0, right, self._integration_steps)
        integral = np.zeros_like(z_val)
        
        B_max = self.B_field(r, right)

        for i in range(len(z_val)):
            integral[i] = quad(lambda z: 1/np.sqrt(B_max-self.B_field(r, z)), 0,z_val[i])[0]

        t = integral * np.sqrt(B_max)/get_relativistic_velocity(electron.E_kin)

        interpolation = make_interp_spline(t, z_val, bc_type='clamped')
        
        def z_f(t_in):
            
            #periodical continuation under the assumption that the integral
            #scans the first quarter period of the electron trajectory in a symmetric trap
            t_end = t[-1]

            t_out = t_in.copy()
            t_out %= 4*t_end
            t_out[t_out>2*t_end] = t_end - (t_out[t_out>2*t_end]-t_end)
            sign = np.sign(t_out[np.abs(t_out)>t_end])
            t_out[np.abs(t_out)>t_end] = sign*t_end-(t_out[np.abs(t_out)>t_end]-sign*t_end)

            negative = t_out<0
            res = np.empty_like(t_in)
            res[negative] = -interpolation(-t_out[negative])
            res[~negative] = interpolation(t_out[~negative])

            return res
            
        self._T_buffer[electron] = 4*t[-1]
        
        return t, z_val, z_f
