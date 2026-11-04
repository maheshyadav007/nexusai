# Deployment customization

Keep the application source generic. Configure organization-specific mail/model endpoints, update hosting and signing in an ignored local profile, then transfer the profile to the Windows build environment.

```sh
./desktop.sh profile-init
# Edit .release/profile/release.json and .release/profile/company.env locally.
./desktop.sh prepare-profile
```

On Windows, with the matching source checkout and the transferred private bundle:

```powershell
.\desktop.cmd apply-profile -Profile C:\Deploy\deployment.zip
.\desktop.cmd build-test
```

The profile ZIP can contain internal credentials and explicitly configured key files. It is deployment material, not a source/CI artifact. Generic GitHub Windows validation uses no profile. Service defaults are embedded by default; embedding the complete credentials file is a separate explicit profile option.

See the [complete build, validation and release manual](../docs/WINDOWS_RELEASE_GUIDE.md).
