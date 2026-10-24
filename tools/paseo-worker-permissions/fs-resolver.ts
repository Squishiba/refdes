import { lstatSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import type { PathResolver } from "./shared/classifier.ts";

/**
 * Filesystem-backed PathResolver (kept out of index.server.ts so tests can
 * import it under plain node --test; index.server.ts imports this module
 * extensionless, matching the daemon's plugin-loader convention).
 *
 * realpath via realpathSync; for a wildcard pattern, inspect the directory's
 * direct children and report the first symlink whose real target lies
 * outside the realpath'd roots. Missing directory = no children = "clear";
 * any other fs error throws (the classifier fails closed). Above
 * MAX_CHILD_ENTRIES the answer is "too-many" (pending) so a hostile giant
 * directory cannot stall the hook.
 */

export const MAX_CHILD_ENTRIES = 5000;

export function createFsResolver(): PathResolver {
  return {
    realpath: (pathToResolve) => realpathSync(pathToResolve),
    childSymlinkEscapes(dir, resolvedRoots) {
      let names: string[];
      try {
        names = readdirSync(dir);
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (code === "ENOENT" || code === "ENOTDIR") return "clear";
        throw error;
      }
      if (names.length > MAX_CHILD_ENTRIES) return "too-many";
      for (const name of names) {
        const child = path.join(dir, name);
        let isLink = false;
        try {
          isLink = lstatSync(child).isSymbolicLink();
        } catch (error) {
          throw new Error(`lstat failed for ${child}: ${String((error as Error).message)}`);
        }
        if (!isLink) continue;
        let target: string;
        try {
          target = realpathSync(child);
        } catch {
          throw new Error(`dangling symlink ${child}: real target unknown`);
        }
        const inside = resolvedRoots.some(
          (root) => target === root || target.startsWith(`${root}/`),
        );
        if (!inside) return "escape";
      }
      return "clear";
    },
  };
}
