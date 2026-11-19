#include <iomanip>
#include <iostream>
#include <winrt/Windows.UI.ViewManagement.h>
#include <winrt/Windows.UI.h>
#include <winrt/base.h>

#pragma comment(lib, "windowsapp.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")

int main() {
    winrt::init_apartment();
    try {
        winrt::Windows::UI::ViewManagement::UISettings settings;
        const auto color = settings.GetColorValue(
            winrt::Windows::UI::ViewManagement::UIColorType::Accent);
        std::cout << std::fixed << std::setprecision(6)
                  << "{\"source\":\"UISettings.GetColorValue(Accent)\",\"rgb\":["
                  << static_cast<double>(color.R) / 255.0 << ','
                  << static_cast<double>(color.G) / 255.0 << ','
                  << static_cast<double>(color.B) / 255.0 << "]}" << std::endl;
        return 0;
    } catch (const winrt::hresult_error& error) {
        std::cerr << "UISettings read failed: " << winrt::to_string(error.message()) << std::endl;
        return 2;
    }
}
