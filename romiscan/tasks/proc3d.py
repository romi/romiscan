import luigi
import numpy as np

from romidata.task import  RomiTask, FileByFileTask
from romidata import io

from romiscan.tasks.cl import Voxels

import logging
logger = logging.getLogger('romiscan')

class PointCloud(RomiTask):
    """Computes a point cloud
    """
    upstream_task = luigi.TaskParameter(default=Voxels)
    level_set_value = luigi.FloatParameter(default=0.0)

    def run(self):
        from romiscan import proc3d
        ifile = self.input_file()
        if Voxels.multiclass:
            import open3d
            voxels = io.read_npz(ifile)
            l = list(voxels.keys())
            res = np.zeros((*voxels[l[0]].shape, len(l)))

            for i in range(len(l)):
                res[:,:,:,i] = voxels[l[i]]

            res = np.argmax(res, axis=3)
            pcd = open3d.geometry.PointCloud()
            origin = np.array(ifile.get_metadata('origin'))

            voxel_size = float(ifile.get_metadata('voxel_size'))
            labels = []

            for i in range(len(l)):
                if l[i] != 'background':
                    out = proc3d.vol2pcd(res == i, origin, voxel_size, self.level_set_value)
                    color = np.zeros((len(out.points), 3))
                    color[:] =np.random.rand(3)[np.newaxis, :]
                    color = open3d.utility.Vector3dVector(color)
                    out.colors = color
                    pcd = pcd + out
                    labels = labels + [l[i] for x in range(len(pcd.points))]

            io.write_point_cloud(self.output_file(), pcd)
            self.output_file().set_metadata({'labels' : labels})        

        else:
            voxels = io.read_volume(ifile)

            origin = np.array(ifile.get_metadata('origin'))
            voxel_size = float(ifile.get_metadata('voxel_size'))
            out = proc3d.vol2pcd(voxels, origin, voxel_size, self.level_set_value)

            io.write_point_cloud(self.output_file(), out)


class TriangleMesh(RomiTask):
    """Computes a mesh
    """
    upstream_task = luigi.TaskParameter(default=PointCloud)

    def run(self):
        from romiscan import proc3d

        point_cloud = io.read_point_cloud(self.input_file())

        out = proc3d.pcd2mesh(point_cloud)

        io.write_triangle_mesh(self.output_file(), out)


class CurveSkeleton(RomiTask):
    """Computes a 3D curve skeleton
    """
    upstream_task = luigi.TaskParameter(default=TriangleMesh)

    def run(self):
        from romiscan import proc3d

        mesh = io.read_triangle_mesh(self.input_file())

        out = proc3d.skeletonize(mesh)

        io.write_json(self.output_file(), out)

