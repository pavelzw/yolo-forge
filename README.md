# yolo-forge

Some forks/packages of mine as conda packages for easier installation and management.

- [finnvoor/yap](https://github.com/finnvoor/yap) (currently [no Swift support on conda-forge](https://github.com/conda-forge/conda-forge.github.io/issues/2550) so this is just a repackaged version)
- [moshix/moer](https://github.com/moshix/moer) (compiled from source)
- [moshix/web3270](https://github.com/moshix/web3270) (repackaged from the release binaries)
- [moshix/BRICKS_TS](https://github.com/moshix/BRICKS_TS) (repackaged from the release binaries)
- [moshix/3270BBS](https://github.com/moshix/3270BBS) (repackaged from the release binaries)

The full documentation for the recipe format can be found in the [rattler-build documentation](https://rattler.build/latest/reference/recipe_file).

## yap

```bash
pixi global install -c https://prefix.dev/yolo-forge yap-repackaged
```

## moer

```bash
pixi global install -c https://prefix.dev/yolo-forge moer
```

## web3270

```bash
pixi global install -c https://prefix.dev/yolo-forge web3270
```

## bricks

```bash
pixi global install -c https://prefix.dev/yolo-forge bricks
```

## 3270bbs

```bash
pixi global install -c https://prefix.dev/yolo-forge 3270bbs
```
