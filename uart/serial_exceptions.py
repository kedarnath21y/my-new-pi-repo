class SerialError(Exception): pass
class LinkNotOpen(SerialError): pass
class FrameTooLarge(SerialError): pass
class LinkWriteError(SerialError): pass
class LinkReadError(SerialError): pass
