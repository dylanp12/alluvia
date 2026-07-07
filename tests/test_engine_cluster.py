from alluvia.engine.cluster import cluster


def test_two_separated_groups_form_two_clusters():
    # embeddings cluster by DIRECTION (cosine), so separate groups by angle, not
    # magnitude — and avoid the zero vector, whose direction is undefined.
    def pad(x, y):
        return [x, y] + [0.0] * 6
    vecs = [pad(1.0, 0.0), pad(0.95, 0.05), pad(0.9, 0.1),
            pad(0.0, 1.0), pad(0.05, 0.95), pad(0.1, 0.9)]
    labels = cluster(vecs, min_cluster_size=2)
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4] == labels[5]
    assert labels[0] != labels[3]


def test_too_few_points_all_noise():
    assert cluster([[1.0] + [0.0] * 7], min_cluster_size=2) == [-1]
