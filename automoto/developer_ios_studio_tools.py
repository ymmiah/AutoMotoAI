"""iPhone actions for the assistant. Discovered by the studio registry.

The person does not pick these names. Progress is the plain label. Sending to
Apple still needs the button in Developer Studio; this module cannot press it.
"""

from __future__ import annotations

from automoto.studio_registry import S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool


def ios_wizard(ctx) -> str:
    from automoto import developer_ios
    return call_studio(developer_ios.wizard, studio_request("GET"))


def ios_setup(ctx, xcode_xip: str = "") -> str:
    from automoto import developer_ios
    body = developer_ios.SetupIn.model_validate({"xcode_xip": xcode_xip})
    return call_studio(developer_ios.setup, studio_request("POST"), body)


def ios_device(ctx) -> str:
    from automoto import developer_ios
    return call_studio(developer_ios.devices, studio_request("GET"))


def ios_create(ctx, prompt: str = "", project: str = "", zip_path: str = "") -> str:
    from automoto import developer_ios
    body = developer_ios.CreateIn.model_validate({
        "prompt": prompt, "project": project, "zip_path": zip_path,
    })
    return call_studio(developer_ios.create_app, studio_request("POST"), body)


def ios_build(ctx, project: str) -> str:
    from automoto import developer_ios
    body = developer_ios.ProjectIn.model_validate({"project": project})
    return call_studio(developer_ios.build_app, studio_request("POST"), body)


def ios_install(ctx, project: str) -> str:
    from automoto import developer_ios
    body = developer_ios.ProjectIn.model_validate({"project": project})
    return call_studio(developer_ios.install_app, studio_request("POST"), body)


def ios_listing(ctx, project: str, name: str, description: str, privacy: str,
                subtitle: str = "", keywords: str = "", support_url: str = "",
                version: str = "1.0", build_number: str = "1") -> str:
    from automoto import developer_ios
    body = developer_ios.ListingIn.model_validate({
        "project": project, "name": name, "subtitle": subtitle, "description": description,
        "keywords": keywords, "privacy": privacy, "support_url": support_url,
        "version": version, "build_number": build_number,
    })
    return call_studio(developer_ios.prepare_listing, studio_request("POST"), body)


def ios_publish(ctx, project: str, listing_sha256: str) -> str:
    """Send the app only when the person has already pressed Send to Apple for this page."""
    from automoto import developer_ios
    body = developer_ios.SubmitIn.model_validate({"project": project, "listing_sha256": listing_sha256})
    return call_studio(developer_ios.submit_app, studio_request("POST"), body)


_PROJECT = {"project": S}

STUDIO = StudioSpec(
    id="developer-ios",
    name="iPhone apps",
    hosted_ok=False,
    approval="risky",
    host_exec=("ios_setup", "ios_device", "ios_build", "ios_install", "ios_publish"),
    online_only=("ios_publish",),
    words=r"\b(iphone|ios app|app store|xcode\.xip|developer mode)\b",
    skills=("developer-ios",),
    fuzzy=("iphone", "xcode"),
    how="Use ios_wizard first and repeat its plain steps. ios_create writes an app from a prompt or a ZIP "
        "and does not show source. ios_build and ios_install need the person's computer and a real iPhone. "
        "ios_listing writes a draft page and does not send it. ios_publish refuses until the person has "
        "pressed Send to Apple in the iPhone panel for that exact page. Never paste an Apple key, and "
        "never say the app was sent unless the tool result says Apple has it. Do not show code unless asked.",
    labels={
        "ios_wizard": "Explaining the iPhone steps",
        "ios_setup": "Checking the iPhone tools",
        "ios_device": "Looking for your iPhone",
        "ios_create": "Creating the iPhone app",
        "ios_build": "Building the iPhone app",
        "ios_install": "Installing the app on your iPhone",
        "ios_listing": "Writing the App Store page",
        "ios_publish": "Sending the app to Apple",
    },
    tools=(
        Tool("ios_wizard", "Explain the one-time iPhone steps in plain language. Does not build or send anything.",
             obj({}), "safe", ios_wizard),
        Tool("ios_setup", "Check whether this computer can build for an iPhone, and whether an Xcode.xip path looks real. "
             "Does not download an Apple SDK.",
             obj({"xcode_xip": S}), "risky", ios_setup),
        Tool("ios_device", "Look for a plugged-in iPhone. Does not install an app.",
             obj({}), "risky", ios_device),
        Tool("ios_create", "Create an iPhone app from a description or a ZIP already in the workspace. "
             "The reply names the folder and does not include source code.",
             obj({"prompt": S, "project": S, "zip_path": S}), "risky", ios_create),
        Tool("ios_build", "Build the iPhone app. Needs the iPhone tools on this computer.",
             obj(_PROJECT, ["project"]), "risky", ios_build),
        Tool("ios_install", "Install the built app on the plugged-in iPhone.",
             obj(_PROJECT, ["project"]), "risky", ios_install),
        Tool("ios_listing", "Write the App Store page as a draft. Does not upload it.",
             obj({"project": S, "name": S, "description": S, "privacy": S, "subtitle": S,
                  "keywords": S, "support_url": S, "version": S, "build_number": S},
                 ["project", "name", "description", "privacy"]), "risky", ios_listing),
        Tool("ios_publish", "Send the app and the approved page to Apple. Refuses unless the person "
             "already pressed Send to Apple for this exact page. Not available offline.",
             obj({"project": S, "listing_sha256": S}, ["project", "listing_sha256"]), "risky", ios_publish),
    ),
)
