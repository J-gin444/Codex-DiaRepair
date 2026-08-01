"""Standalone entry point for packaged GUI exe."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.interfaces import launch_gui
launch_gui()
