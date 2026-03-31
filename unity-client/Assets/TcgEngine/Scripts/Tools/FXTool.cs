using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.FX;
using TcgEngine.Client;

namespace TcgEngine
{
    /// <summary>
    /// Static functions to spawn FX prefabs
    /// </summary>

    public class FXTool : MonoBehaviour
    {
        public static GameObject DoFX(GameObject fx_prefab, Vector3 pos, float duration = 5f)
        {
            if (fx_prefab != null)
            {
                GameObject fx = Instantiate(fx_prefab, pos, GetFXRotation());
                Destroy(fx, duration);
                return fx;
            }
            return null;
        }

        public static GameObject DoSnapFX(GameObject fx_prefab, Transform snap_target)
        {
            return DoSnapFX(fx_prefab, snap_target, Vector3.zero);
        }

        public static GameObject DoSnapFX(GameObject fx_prefab, Transform snap_target, Vector3 offset)
        {
            if (fx_prefab != null && snap_target != null)
            {
                GameObject fx = Instantiate(fx_prefab, snap_target.transform.position + offset, GetFXRotation());
                SnapFX snap = fx.AddComponent<SnapFX>();
                snap.target = snap_target;
                snap.offset = offset;
                Destroy(fx, 5f);
                return fx;
            }
            return null;
        }

        public static GameObject DoProjectileFX(GameObject fx_prefab, Transform source, Transform target, int damage)
        {
            if (fx_prefab != null && source != null && target != null)
            {
                GameObject fx = Instantiate(fx_prefab, source.position, GetFXRotation());
                Projectile projectile = fx.GetComponent<Projectile>();
                if (projectile == null)
                    projectile = fx.AddComponent<Projectile>();

                projectile.SetSource(source);
                projectile.SetTarget(target);
                projectile.damage = damage;
                projectile.DelayDamage();

                Destroy(fx, projectile.duration);
                return fx;
            }
            return null;
        }

        private static Quaternion GetFXRotation()
        {
            GameBoard board = GameBoard.Get();
            Vector3 facing = board != null ? board.transform.forward : Vector3.forward;
            return Quaternion.LookRotation(facing, Vector3.up);
        }
    }
}
