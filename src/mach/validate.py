import re
from typing import List

import click
from mach import types
from mach.exceptions import ValidationError

STORE_KEY_RE = re.compile(r"^[\w_-]*$")


def validate_config(config: types.MachConfig):
    """Check the config for invalid configuration."""
    validate_general_config(config.general_config)
    validate_components(config)

    for site in config.sites:
        validate_site(site, config=config)


def validate_general_config(config: types.GeneralConfig):
    if config.cloud == types.CloudOption.AZURE:
        if not config.azure:
            raise ValidationError("Missing azure configuration")
        if not config.terraform_config.azure_remote_state:
            raise ValidationError("Missing azure_remote_state configuration")
        if config.terraform_config.aws_remote_state:
            raise ValidationError(
                "Found aws_remote_state configuration, while cloud is set to 'azure'"
            )
    elif config.cloud == types.CloudOption.AWS:
        if not config.terraform_config.aws_remote_state:
            raise ValidationError("Missing aws_remote_state configuration")
        if config.terraform_config.azure_remote_state:
            raise ValidationError(
                "Found azure_remote_state configuration, while cloud is set to 'aws'"
            )

    if config.terraform_config:
        validate_terraform_config(config.terraform_config)

    if config.sentry:
        validate_sentry_config(config.sentry)


def validate_terraform_config(config: types.TerraformConfig):
    if config.providers:
        click.secho("Terraform provider versions", bold=True, fg="yellow")
        click.secho(
            "\n".join(
                [
                    "You are using custom Terraform provider versions.",
                    "Please be aware that some unexpected changes might occur compared to the MACH defaults.",  # noqa
                ]
            ),
            fg="yellow",
        )


def validate_site(site: types.Site, *, config: types.MachConfig):
    if config.general_config.cloud == types.CloudOption.AWS and not site.aws:
        raise ValidationError(f"Site {site.identifier} is missing an aws configuration")

    validate_endpoints(site, config.general_config.cloud)
    validate_commercetools(site)

    if site.components:
        validate_site_components(site.components, site=site)


def validate_endpoints(site: types.Site, cloud: types.CloudOption):
    dns_zone = None

    if site.endpoints:
        # Construct lookup dictionary of all endpoints with the components that use them
        if cloud == types.CloudOption.AWS:
            dns_zone = site.aws.route53_zone_name
            if not dns_zone:
                raise ValidationError(
                    f"Site {site.identifier} needs to have a route53_zone_name "
                    "defined before endpoints can be used."
                )

        elif cloud == types.CloudOption.AZURE:
            if not site.azure.frontdoor:
                raise ValidationError(
                    f"Site {site.identifier} needs to have a Frontdoor dns_zone "
                    "defined before endpoints can be used."
                )

            dns_zone = site.azure.frontdoor.dns_zone

        for endpoint in site.endpoints:
            if not endpoint.url.endswith(dns_zone):
                raise ValidationError(
                    f"No match between endpoint {endpoint} and DNS zone {dns_zone}"
                )

    expected_endpoint_names = {c.endpoint for c in site.components if c.endpoint}
    endpoint_names = {e.key for e in site.endpoints}

    if cloud == types.CloudOption.AZURE:
        # In Azure, we can create a Frontdoor instance without specifying a specific domain.
        # If no custom domains are needed, a component can define their endpoint with 'default',
        # indicating that it does need an endpoint, but doesnt need to be one defined in the site
        # definition
        endpoint_names |= {"default"}

    missing = expected_endpoint_names - endpoint_names
    if missing:
        raise ValidationError(f"Missing required endpoints {', '.join(missing)}")


def validate_site_components(components: List[types.Component], *, site: types.Site):
    """Sanity checks on component configuration per site."""
    defined_stores = (
        [s.key for s in site.commercetools.stores] if site.commercetools else []
    )

    for component in components:
        if component.health_check_path and not component.health_check_path.startswith(
            "/"
        ):
            raise ValidationError(
                f"Component health check {component.health_check_path} does "
                "not start with '/'."
            )

        for store in component.store_variables.keys():
            if store not in defined_stores:
                raise ValidationError(
                    f"Store {store} is not defined in your commercetools stores definition"
                )


def validate_commercetools(site: types.Site):
    if site.commercetools:
        validate_store_keys(site.commercetools)


def validate_store_keys(ct_settings: types.CommercetoolsSettings):
    """Sanity checks on store values."""
    if ct_settings.stores:
        store_keys = [store.key for store in ct_settings.stores]
        for key in store_keys:
            if len(key) < 2:
                raise ValidationError(
                    f"Store key {key} should be minimum two characters."
                )
            if store_keys.count(key) != 1:
                raise ValidationError(f"Store key {key} must be unique.")

            if not STORE_KEY_RE.match(key):
                raise ValidationError(
                    f"Store key {key} may only contain alphanumeric characters or underscores"
                )


def validate_components(config: types.MachConfig):
    """Validate global component data is valid."""
    if config.general_config.cloud == types.CloudOption.AWS:
        validate_aws_components(config)
    elif config.general_config.cloud == types.CloudOption.AZURE:
        validate_azure_components(config)


def validate_sentry_config(config: types.SentryConfig):
    if not any([config.dsn, config.auth_token]):
        raise ValidationError("sentry: Either dsn or auth_token should be set")

    if all([config.dsn, config.auth_token]):
        raise ValidationError("sentry: Only a dsn or auth_token should be defined")

    if config.auth_token and not any([config.project, config.organization]):
        raise ValidationError(
            "sentry: A project and organization should be defined when using an auth_token"
        )


def validate_aws_components(config: types.MachConfig):
    """Validate components specifically for AWS usage."""
    pass


def validate_azure_components(config: types.MachConfig):
    """Validate components specifically for Azure usage.

    Only requirements for now is that a correct short_name should be set.
    Otherwise problems will arise when creating the Azure resources since
    for example Storage Accounts names have a limited length.
    """
    for comp in config.components:
        if "azure" not in comp.integrations:
            continue

        # azure naming length is limited, so verify it doesn't get too long.
        if len(comp.short_name) > 10:
            raise ValidationError(
                f"Component ({comp.name}) short name '{comp.short_name}' "
                "cannot be more than 10 characters."
            )
