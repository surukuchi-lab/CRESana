

"""

Author: F. Thomas
Date: August 11, 2021

"""

__all__ = []

import numpy as np


def get_pos(x, y, z):
    return np.vstack((x,y,z)).transpose()
    

def norm_squared(x):
    return np.sum(x**2, axis=-1)
    
    
def calc_aliased_frequencies(frequencies, sr):
	
	n = np.round(frequencies/sr)
	
	return np.abs(sr*n-frequencies)
