import unittest,tempfile,zipfile,importlib.util,json,tarfile,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('setup_assets',ROOT/'scripts/setup_assets.py');assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.original=assets.ROOT;assets.ROOT=self.root;self.addCleanup(setattr,assets,'ROOT',self.original)
    def test_zip_traversal_refused(self):
        archive=self.root/'bad.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside.txt','bad')
        with self.assertRaises(ValueError):assets.extract_zip(archive,self.root/'out')
        self.assertFalse((self.root/'outside.txt').exists())
    def test_zip_existing_modified_file_preserved(self):
        archive=self.root/'ok.zip';dest=self.root/'out';dest.mkdir();(dest/'one.txt').write_text('user edit')
        with zipfile.ZipFile(archive,'w') as z:z.writestr('one.txt','upstream')
        with self.assertRaises(RuntimeError):assets.extract_zip(archive,dest)
        self.assertEqual((dest/'one.txt').read_text(),'user edit')
    def test_existing_mismatched_asset_not_overwritten(self):
        target=self.root/'model';target.write_bytes(b'keep')
        with self.assertRaises(RuntimeError):assets.download({'path':'model','size':4,'sha256':'0'*64,'url':'https://example.com/not-used'})
        self.assertEqual(target.read_bytes(),b'keep')
    def test_tar_traversal_refused(self):
        archive=self.root/'bad.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            entry=tarfile.TarInfo('source/../outside.txt');entry.size=3;tar.addfile(entry,io.BytesIO(b'bad'))
        with self.assertRaises(ValueError):assets.extract_tar(archive,self.root/'out')
        self.assertFalse((self.root/'outside.txt').exists())
