def load_dicom(path):
    import pydicom
    return pydicom.dcmread(path, force=True)
