import luigi
import numpy as np

from romidata.task import  RomiTask, FileByFileTask
from romidata import io

from romiscan.tasks.cl import Voxels
from romiscan.tasks.colmap import Colmap
from romiscan.tasks.proc2d import Segmentation2D
from romiscan import proc3d
from romiscan.tasks import config

from scipy.ndimage import gaussian_filter

import logging
logger = logging.getLogger('romiscan')


class PointCloud(RomiTask):
    """Computes a point cloud
    """
    upstream_task = luigi.TaskParameter(default=Voxels)
    level_set_value = luigi.FloatParameter(default=0.0)
    log = luigi.BoolParameter(default=False)
    background_prior = luigi.FloatParameter(default=1.0)
    min_contrast = luigi.FloatParameter(default=10.0)
    min_score = luigi.FloatParameter(default=0.2)

    def run(self):
        from romiscan import proc3d
        ifile = self.input_file()

        try:
            voxels = io.read_npz(ifile)
            if (len(voxels.keys()) == 1):
                multiclass = False
                voxels = voxels[list(voxels.keys())[0]]
            else:
                multiclass = True
        except:
            voxels = io.read_volume(ifile)
            multiclass = False
        if multiclass:
            import open3d
            l = list(voxels.keys())
            # background_idx = l.index("background")
            # l.remove("background")
            res = np.zeros((*voxels[l[0]].shape, len(l)))
            for i in range(len(l)):
                res[:,:,:,i] = voxels[l[i]]
            for i in range(len(l)):
                if l[i] == 'background':
                    res[:,:,:,i] *= self.background_prior


            # bg = voxels["background"] > voxels["background"].max() - 10

            res_idx = np.argmax(res, axis=3)
            # res_value = np.amax(res, axis=3)

            # threshold= np.quantile(res_value.flatten(), 0.99)
            # res_idx[res_value < threshold] = background_idx # low scores belong to background

            pcd = open3d.geometry.PointCloud()
            origin = np.array(ifile.get_metadata('origin'))

            voxel_size = float(ifile.get_metadata('voxel_size'))
            point_labels = []
            colors = config.PointCloudColorConfig().colors

            for i in range(len(l)):
                logger.debug(f"label = {l[i]}")
                if l[i] != 'background':
                    pred_no_c = np.copy(res)
                    pred_no_c = np.max(np.delete(res, i, axis=3), axis=3)
                    pred_c = res[:,:,:,i]
                    pred_c = (res_idx == i)
                    if self.min_contrast > 1.0:
                        pred_c *= (pred_c > (self.min_contrast * pred_no_c))
                    pred_c *= (pred_c > self.min_score)

                    out = proc3d.vol2pcd(pred_c, origin, voxel_size, self.level_set_value)
                    color = np.zeros((len(out.points), 3))
                    if l[i] in colors:
                        color[:] = np.asarray(colors[l[i]])
                    else:
                        color[:] = np.random.rand(3)
                    color = open3d.utility.Vector3dVector(color)
                    out.colors = color
                    pcd = pcd + out
                    point_labels = point_labels + [l[i]] * len(out.points)

            io.write_point_cloud(self.output_file(), pcd)
            self.output_file().set_metadata({'labels' : point_labels})
            

        else:
            origin = np.array(ifile.get_metadata('origin'))
            voxel_size = float(ifile.get_metadata('voxel_size'))
            out = proc3d.vol2pcd(voxels, origin, voxel_size, self.level_set_value)

            io.write_point_cloud(self.output_file(), out)
            self.output_file().set_metadata({'voxel_size': voxel_size})

class SegmentedPointCloud(RomiTask):
    """ Segments an existing point cloud using 2D pictures
    """
    upstream_task = luigi.TaskParameter(default=Colmap)
    upstream_segmentation = luigi.TaskParameter(default=Segmentation2D)
    use_colmap_poses = luigi.BoolParameter(default=True)



    def requires(self):
        return [self.upstream_task(), self.upstream_segmentation()]

    def load_point_cloud(self):
        try:
            x = self.requires()[0].output().get().get_file("dense")
            return io.read_point_cloud(x)
        except:
            x = self.requires()[0].output().get().get_files()[0]
            return io.read_point_cloud(x)

    def is_in_pict(self, px, shape):
        return px[0] > 0 and px[0] < shape[1] and px[1] > 0 and px[1] < shape[0]


    def run(self):
        import open3d
        fs = self.upstream_segmentation().output().get()
        pcd = self.load_point_cloud()
        pts = np.asarray(pcd.points)
        ifile = self.input_file()

        labels = set()
        for fi in fs.get_files():
            label = fi.get_metadata('channel')
            if label is not None:
                labels.add(label)
        labels = list(labels)
        logger.critical(labels)
        labels.remove('background')
        if 'rgb' in labels:
            labels.remove('rgb')

        scores = np.zeros((len(labels), len(pts)))

        for fi in fs.get_files():
            label = fi.get_metadata("channel")
            if label not in labels:
                continue

            if self.use_colmap_poses:
                camera = fi.get_metadata("colmap_camera")
            else:
                camera = fi.get_metadata("camera")

            if camera is None:
                logger.warning("Could not get camera pose for view, skipping...")
                continue

            rotmat = np.array(camera["rotmat"])
            tvec = np.array(camera["tvec"])

            intrinsics = camera["camera_model"]["params"]
            K = np.array([[intrinsics[0], 0, intrinsics[2]], [0, intrinsics[1], intrinsics[3]], [0, 0, 1]])
            pixels = np.asarray(proc3d.backproject_points(pts, K, rotmat, tvec) + 0.5, dtype=int)
            
            label_idx = labels.index(label)
            mask = io.read_image(fi)
            for i, px in enumerate(pixels):
                if self.is_in_pict(px, mask.shape):
                    
                    scores[label_idx, i] += mask[px[1], px[0]]


        pts_labels = np.argmax(scores, axis=0).flatten()

        colors = config.PointCloudColorConfig().colors
        color_array = np.zeros((len(pts), 3))
        point_labels = [""] * len(pts)
        logger.critical(labels)
        logger.critical(colors)
        for i in range(len(labels)):
            logger.critical((pts_labels==i).sum())
            if labels[i] in colors:
                color_array[pts_labels==i, :] = np.asarray(colors[labels[i]])
            else:
                color_array[pts_labels==i, :] = np.random.rand(3)
            l = np.nonzero(pts_labels==i)[0].tolist()
            for u in l:
                point_labels[u] = labels[i]
        pcd.colors = open3d.utility.Vector3dVector(color_array)
        out = self.output_file()
        io.write_point_cloud(out, pcd)
        out.set_metadata("labels", point_labels)



class TriangleMesh(RomiTask):
    """Computes a mesh
    """
    upstream_task = luigi.TaskParameter(default=PointCloud)

    def run(self):
        from romiscan import proc3d

        point_cloud = io.read_point_cloud(self.input_file())

        out = proc3d.pcd2mesh(point_cloud)

        io.write_triangle_mesh(self.output_file(), out)

class ClusteredMesh(RomiTask):
    upstream_task = luigi.TaskParameter(default=PointCloud)

    min_vol = luigi.FloatParameter(default=1.0)
    min_length = luigi.FloatParameter(default=10.0)

    def run(self):
        from sklearn.cluster import DBSCAN, SpectralClustering
        import open3d
        x = io.read_point_cloud(self.input_file())
        all_points = np.asarray(x.points)
        all_normals = np.asarray(x.normals)
        all_colors = np.asarray(x.colors)

        labels = self.input_file().get_metadata("labels")

        geometries = []
        output_fileset = self.output().get()

        for l in set(labels):
            pcd = open3d.geometry.PointCloud()
            idx = [i for i in range(len(labels)) if labels[i] == l]
            points = all_points[idx, :]
            normals = all_normals[idx, :]
            colors = all_colors[idx, :]
            if len(points > 0):
                pcd.points = open3d.utility.Vector3dVector(points)
                pcd.normals = open3d.utility.Vector3dVector(normals)
                pcd.colors = open3d.utility.Vector3dVector(colors)

                t, _ = open3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd)
                t.compute_adjacency_list()
                k, cc, _ = t.cluster_connected_triangles()
                k = np.asarray(k)
                tri_np = np.asarray(t.triangles)
                for j in range(len(cc)):
                    newt = open3d.geometry.TriangleMesh(t.vertices, open3d.utility.Vector3iVector(tri_np[k==j, :]))
                    newt.vertex_colors = t.vertex_colors
                    newt.remove_unreferenced_vertices()

                    f = output_fileset.create_file("%s_%03d"%(l, j))
                    io.write_triangle_mesh(f, newt)
                    f.set_metadata("label", l)

class CurveSkeleton(RomiTask):
    """Computes a 3D curve skeleton
    """
    upstream_task = luigi.TaskParameter(default=TriangleMesh)

    def run(self):
        from romiscan import proc3d

        mesh = io.read_triangle_mesh(self.input_file())

        out = proc3d.skeletonize(mesh)

        io.write_json(self.output_file(), out)


class VoxelsWithPrior(RomiTask):
    """
    Assign class to voxel adjusting for the possibility that
    projection can be wrongly labeled.
    """
    upstream_task = luigi.TaskParameter(default=Voxels)
    recall = luigi.DictParameter(default={})
    specificity = luigi.DictParameter(default={})
    n_views = luigi.IntParameter()

    def run(self):
        prediction_file = self.upstream_task().output().get().get_files()[0]
        voxels = io.read_npz(prediction_file)
        out = {}
        l = list(voxels.keys())
        for c in l:
            if c in self.recall:
                recall = self.recall[c]
            else:
                continue
            if c in self.specificity:
                specificity = self.specificity[c]
            else:
                continue
            l0 = (self.n_views - voxels[c]) * np.log(specificity) + voxels[c] * np.log(1 - specificity)
            l1 = (self.n_views - voxels[c]) * np.log(1 - recall) + voxels[c] * np.log(recall)
            out[c] = l1 - l0

        outfs = self.output().get()
        outfile = self.output_file()
        io.write_npz(outfile, out)
        outfile.set_metadata(prediction_file.get_metadata())
