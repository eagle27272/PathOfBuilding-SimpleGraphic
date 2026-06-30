#include <string_view>
#include <CoreFoundation/CFBundle.h>
#include <ApplicationServices/ApplicationServices.h>

#include "common.h"

const char* PlatformOpenURL(const char* textUrl)
{
    std::string_view urlView = textUrl;
    CFURLRef url = CFURLCreateWithBytes(nullptr, (const UInt8*)urlView.data(), urlView.size(), kCFStringEncodingUTF8, nullptr);
    if (!url) {
        return AllocString("Could not create URL.");
    }
    OSStatus result = LSOpenCFURLRef(url, nullptr);
    CFRelease(url);
    if (result != noErr) {
        return AllocString("Could not open URL.");
    }
    return nullptr;
}
