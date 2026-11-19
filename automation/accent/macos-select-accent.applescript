-- Disposable hosted runner: select an exact accessible colour label and verify it independently.
on run argv
    if (count of argv) is 0 then error "Pass an accent label such as Purple or Orange."
    set targetLabel to item 1 of argv
    tell application "System Settings" to activate
    open location "x-apple.systempreferences:com.apple.Appearance-Settings.extension"
    set observed to ""
    tell application "System Events"
        tell process "System Settings"
            set frontmost to true
            set deadline to (current date) + 25
            repeat while (current date) is less than deadline
                if (count of windows) > 0 then
                    set candidates to entire contents of window 1
                    set observed to ""
                    repeat with candidate in candidates
                        try
                            set candidateRole to role of candidate as text
                            set candidateName to name of candidate as text
                            set candidateDescription to description of candidate as text
                            set candidateHelp to ""
                            set candidateIdentifier to ""
                            set candidateValue to ""
                            try
                                set candidateHelp to value of attribute "AXHelp" of candidate as text
                            end try
                            try
                                set candidateIdentifier to value of attribute "AXIdentifier" of candidate as text
                            end try
                            try
                                set candidateValue to value of attribute "AXValue" of candidate as text
                            end try
                            set observed to observed & candidateRole & " | " & candidateName & " | " & candidateDescription & " | help=" & candidateHelp & " | id=" & candidateIdentifier & " | value=" & candidateValue & linefeed
                            if candidateName is targetLabel or candidateDescription is targetLabel or candidateHelp is targetLabel then
                                if candidateRole is "AXRadioButton" or candidateRole is "AXButton" then
                                    click candidate
                                    delay 1
                                    return "selected:" & targetLabel & linefeed & observed
                                end if
                            end if
                        end try
                    end repeat
                end if
                delay 0.25
            end repeat
        end tell
    end tell
    error "Accent label not found in the Appearance accessibility tree: " & targetLabel & linefeed & observed
end run
